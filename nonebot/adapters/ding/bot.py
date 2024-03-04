from __future__ import annotations
from typing import TYPE_CHECKING, Any, Union
from typing_extensions import override

from nonebot.message import handle_event
from nonebot.adapters import Bot as BaseBot

from .event import ConversationType, Event
from .message import Message, MessageSegment

if TYPE_CHECKING:
    from .adapter import Adapter


class Bot(BaseBot):
    """
    your_adapter_name 协议 Bot 适配。
    """

    @override
    def __init__(self, adapter: Adapter, self_id: str, **kwargs: Any):
        super().__init__(adapter, self_id)
        self.adapter: Adapter = adapter
        # 一些有关 Bot 的信息也可以在此定义和存储

    async def handle_event(self, event: Event):
        # 根据需要，对事件进行某些预处理，例如：
        # 检查事件是否和机器人有关操作，去除事件消息首尾的 @bot
        # 检查事件是否有回复消息，调用平台 API 获取原始消息的消息内容
        # 调用 handle_event 让 NoneBot 对事件进行处理
        await handle_event(self, event)

    @override
    async def send(
        self,
        event: Event,
        message: Union[str, Message, MessageSegment],
        **kwargs: Any,
    ) -> Any:
        # 根据平台实现 Bot 回复事件的方法

        # 将消息处理为平台所需的格式后，调用发送消息接口进行发送，例如：
        msg = message if isinstance(message, Message) else Message(message)

        data = {}
        data["event"] = event
        data.update(kwargs)

        if event.conversationType != ConversationType.private:
            data["message"] = f"@{event.senderId} " + msg + MessageSegment.atDingtalkIds(event.senderId)
        else:
            data["message"] = msg

        return await self.send_message(**data)
