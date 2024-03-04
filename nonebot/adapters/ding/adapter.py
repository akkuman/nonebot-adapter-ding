import asyncio
from datetime import datetime
import json
import time
from typing import Any
import urllib.parse
from typing_extensions import override
from typing import Any, Tuple, Union, Optional
from nonebot.drivers import Driver
from nonebot.log import logger
from nonebot import get_plugin_config
from nonebot.utils import escape_tag
from nonebot.adapters import Adapter as BaseAdapter
from nonebot.drivers import URL, Driver, Request, Response, HTTPServerSetup

from .config import Config
from .utils import calc_hmac_base64, log
from .bot import Bot
from .event import PrivateMessageEvent, GroupMessageEvent, ConversationType
from .exception import ActionFailed, ApiNotAvailable, NetworkError, SessionExpired
from .message import Message


class Adapter(BaseAdapter):
    @override
    def __init__(self, driver: Driver, **kwargs: Any):
        super().__init__(driver, **kwargs)
        # 读取适配器所需的配置项
        self.adapter_config: Config = get_plugin_config(Config)
        self.setup()

    @classmethod
    @override
    def get_name(cls) -> str:
        """适配器名称"""
        return "Ding"
    
    def setup(self) -> None:
        url_path = self.adapter_config.ding_webhook_urlpath or '/ding'
        self.setup_http_server(
            HTTPServerSetup(
                URL(url_path),
                'POST',
                self.get_name(),
                self._handle_http,
            )
        )

    def _check_signature(self, request: Request) -> bool:
        """
        :说明:

          钉钉协议鉴权。参考 `鉴权 <https://ding-doc.dingtalk.com/doc#/serverapi2/elzz1p>`_
        """
        timestamp = request.headers.get("timestamp")
        sign = request.headers.get("sign")

        # 检查 sign
        secret = self.adapter_config.secret
        sign_base64 = calc_hmac_base64(str(timestamp), secret)
        if sign != sign_base64.decode('utf-8'):
            log("WARNING", "Signature Header is invalid")
            return False
        return True

    async def _handle_http(self, request: Request):
        if not self._check_signature(request):
            return Response(401)
        if data := request.content:
            json_data = json.loads(data)
            bot_id = json_data['chatbotCorpId']
            bot = self.bots.get(bot_id, None)
            if not bot:
                bot = Bot(self, bot_id)
                self.bot_connect(bot)
                log("INFO", f"<y>Bot {escape_tag(bot_id)}</y> connected")
            # 判断消息类型，生成不同的 Event
            try:
                conversation_type = json_data["conversationType"]
                if conversation_type == ConversationType.private:
                    event = PrivateMessageEvent.parse_obj(json_data)
                elif conversation_type == ConversationType.group:
                    event = GroupMessageEvent.parse_obj(json_data)
                else:
                    raise ValueError("Unsupported conversation type")
            except Exception as e:
                log("ERROR", "Event Parser Error", e)
                return

            try:
                asyncio.create_task(bot.handle_event(event))
            except Exception as e:
                logger.opt(colors=True, exception=e).error(
                    f"<r><bg #f8bbd0>Failed to handle event. Raw: {escape_tag(str(json_data))}</bg #f8bbd0></r>"
                )
        else:
            return Response(400, content="Invalid request body")
        return Response(204)
    
    @override
    async def _call_api(self, bot: Bot, api: str, **data) -> Any:
        log("DEBUG", f"Calling API <y>{api}</y>")
        params = {}
        # 传入参数有 webhook，则使用传入的 webhook
        webhook = data.get("webhook")

        if webhook:
            secret = data.get("secret")
            if secret:
                # 有这个参数的时候再计算加签的值
                timestamp = str(round(time.time() * 1000))
                params["timestamp"] = timestamp
                hmac_code_base64 = calc_hmac_base64(timestamp, secret)
                sign = urllib.parse.quote_plus(hmac_code_base64)
                params["sign"] = sign
        else:
            # webhook 不存在则使用 event 中的 sessionWebhook
            event = data.get("event")
            if event:
                # 确保 sessionWebhook 没有过期
                # 默认过期时间是1.5h后
                if int(datetime.now().timestamp()) > int(event.sessionWebhookExpiredTime / 1000):
                    raise SessionExpired

                webhook = event.sessionWebhook
            else:
                raise ApiNotAvailable

        headers = {
            'Content-Type': 'application/json',
        }
        message: Message = data.get("message", None)
        if not message:
            raise ValueError("Message not found")
        request = Request(
            "POST",
            webhook,
            headers=headers,
            params=params,
            timeout=self.config.api_timeout,
            content=json.dumps(message._produce()),
        )
        try:
            response = await self.request(request)

            if 200 <= response.status_code < 300:
                if not response.content:
                    raise ValueError("Empty response")
                result = json.loads(response.content)
                if isinstance(result, dict):
                    if result.get("errcode") != 0:
                        raise ActionFailed(errcode=result.get("errcode"),
                                           errmsg=result.get("errmsg"))
                    return result
            raise NetworkError(f"HTTP request received unexpected "
                               f"status code: {response.status_code}")
        except Exception as e:
            raise NetworkError("HTTP request failed") from e
