from typing import List, Sequence

from autogen_core.base import CancellationToken
from autogen_core.components import FunctionCall
from autogen_core.components.models import (
    AssistantMessage,
    ChatCompletionClient,
    FunctionExecutionResultMessage,
    LLMMessage,
    SystemMessage,
    UserMessage,
)
from autogen_core.components.tools import Tool

from ._base_chat_agent import (
    BaseToolUseChatAgent,
    ChatMessage,
    MultiModalMessage,
    StopMessage,
    TextMessage,
    ToolCallMessage,
    ToolCallResultMessage,
)


class ToolUseAssistantAgent(BaseToolUseChatAgent):
    """An agent that provides assistance with tool use.

    It responds with a StopMessage when 'terminate' is detected in the response.
    """

    def __init__(
        self,
        name: str,
        model_client: ChatCompletionClient,
        registered_tools: List[Tool],
        *,
        description: str = "An agent that provides assistance with ability to use tools.",
        system_message: str = "You are a helpful AI assistant. Solve tasks using your tools. Reply with 'TERMINATE' when the task has been completed.",
    ):
        super().__init__(name=name, description=description, registered_tools=registered_tools)
        self._model_client = model_client
        self._system_messages = [SystemMessage(content=system_message)]
        self._tool_schema = [tool.schema for tool in registered_tools]
        self._model_context: List[LLMMessage] = []

    async def on_messages(self, messages: Sequence[ChatMessage], cancellation_token: CancellationToken) -> ChatMessage:
        # Add messages to the model context.
        for msg in messages:
            if isinstance(msg, ToolCallResultMessage):
                self._model_context.append(FunctionExecutionResultMessage(content=msg.content))
            elif not isinstance(msg, TextMessage | MultiModalMessage | StopMessage):
                raise ValueError(f"Unsupported message type: {type(msg)}")
            else:
                self._model_context.append(UserMessage(content=msg.content, source=msg.source))

        # Generate an inference result based on the current model context.
        llm_messages = self._system_messages + self._model_context
        result = await self._model_client.create(
            llm_messages, tools=self._tool_schema, cancellation_token=cancellation_token
        )

        # Add the response to the model context.
        self._model_context.append(AssistantMessage(content=result.content, source=self.name))

        # Detect tool calls.
        if isinstance(result.content, list) and all(isinstance(item, FunctionCall) for item in result.content):
            return ToolCallMessage(content=result.content, source=self.name)

        assert isinstance(result.content, str)
        # Detect stop request.
        request_stop = "terminate" in result.content.strip().lower()
        if request_stop:
            return StopMessage(content=result.content, source=self.name)

        return TextMessage(content=result.content, source=self.name)