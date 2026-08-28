from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


class Capability(str, Enum):
    RECEIVE_MESSAGE = "receive_message"
    SEND_MESSAGE = "send_message"
    CREATE_SPACE = "create_space"
    UPDATE_SPACE = "update_space"
    DELETE_SPACE = "delete_space"
    LIST_SPACES = "list_spaces"
    RECEIVE_SPACE_EVENTS = "receive_space_events"  # channel/group create/update/delete
    MEDIA = "media"
    THREADS = "threads"


@dataclass
class AdapterCapabilities:
    """Declares exactly what the official API allows. NOT_SUPPORTED => manual fallback."""
    states: Dict[str, str] = field(default_factory=dict)

    def is_supported(self, cap: Capability) -> bool:
        return self.states.get(cap.value) == "supported"

    def is_manual(self, cap: Capability) -> bool:
        return self.states.get(cap.value) == "manual"

    def state(self, cap: Capability) -> str:
        return self.states.get(cap.value, "not_supported")


@dataclass
class OutboundMessage:
    channel_id: str
    content: str
    author_name: str
    message_type: str = "text"
    media_url: Optional[str] = None
    reply_to: Optional[str] = None


@dataclass
class SpaceInfo:
    space_id: str
    name: str
    parent_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class PlatformAdapter(ABC):
    """Base contract. Each platform implements ONLY what its official API supports."""

    platform: str = "base"
    capabilities: AdapterCapabilities = AdapterCapabilities()

    @abstractmethod
    async def send_message(self, msg: OutboundMessage) -> str:
        """Return the platform message id of the sent message."""

    @abstractmethod
    async def list_spaces(self) -> List[SpaceInfo]:
        ...

    @abstractmethod
    async def create_space(self, name: str, parent_id: Optional[str] = None) -> SpaceInfo:
        ...

    async def update_space(self, space_id: str, **kwargs) -> SpaceInfo:
        raise NotImplementedError(f"{self.platform} does not support update_space via official API")

    async def delete_space(self, space_id: str) -> None:
        raise NotImplementedError(f"{self.platform} does not support delete_space via official API")

    @abstractmethod
    def mark_bridge_generated(self, platform_message_id: str) -> None:
        """Record that THIS message was produced by the bridge (loop prevention)."""

    @abstractmethod
    def is_bridge_generated(self, platform_message_id: str) -> bool:
        ...
