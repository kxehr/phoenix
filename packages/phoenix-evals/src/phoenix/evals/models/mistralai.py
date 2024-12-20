from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from phoenix.evals.models.base import BaseModel
from phoenix.evals.models.rate_limiters import RateLimiter
from phoenix.evals.templates import MultimodalPrompt, PromptPartContentType

if TYPE_CHECKING:
    from mistralai.models.chat_completion import ChatMessage

DEFAULT_MISTRAL_MODEL = "mistral-large-latest"
"""Use the latest large mistral model by default."""

MINIMUM_MISTRAL_VERSION = "0.0.11"


class MistralRateLimitError(Exception):
    pass


@dataclass
class MistralAIModel(BaseModel):
    """
    An interface for using MistralAI models.

    This class wraps the MistralAI SDK for use with Phoenix LLM evaluations. Calls to the
    MistralAI API are dynamically throttled when encountering rate limit errors. Requires the
    `mistralai` package to be installed.

    Supports Async: ✅
        If possible, makes LLM calls concurrently.

    Args:
        model (str, optional): The model name to use. Defaults to "mistral-large-latest".
        temperature (float, optional): Sampling temperature to use. Defaults to 0.0.
        top_p (float, optional): Total probability mass of tokens to consider at each step.
            Defaults to None.
        random_seed (int, optional): Random seed to use for sampling. Defaults to None.
        response_format (Dict[str, str], optional): A dictionary specifying the format of the
            response. Defaults to None.
        safe_mode (bool, optional): Whether to use safe mode. Defaults to False.
        safe_prompt (bool, optional): Whether to use safe prompt. Defaults to False.
        initial_rate_limit (int, optional): The initial internal rate limit in allowed requests
            per second for making LLM calls. This limit adjusts dynamically based on rate
            limit errors. Defaults to 5.

    Example:
        .. code-block:: python

            # Get your own Mistral API Key: https://docs.mistral.ai/#api-access
            # Set the MISTRAL_API_KEY environment variable

            from phoenix.evals import MistralAIModel
            model = MistralAIModel(model="mistral-large-latest")
    """

    model: str = DEFAULT_MISTRAL_MODEL
    temperature: float = 0
    top_p: Optional[float] = None
    random_seed: Optional[int] = None
    response_format: Optional[Dict[str, str]] = None
    safe_mode: bool = False
    safe_prompt: bool = False
    initial_rate_limit: int = 5

    def __post_init__(self) -> None:
        self._init_client()
        self._init_rate_limiter()

    @property
    def _model_name(self) -> str:
        return self.model

    def _init_client(self) -> None:
        try:
            from mistralai.async_client import MistralAsyncClient
            from mistralai.client import MistralClient
            from mistralai.exceptions import MistralAPIException
            from mistralai.models.chat_completion import ChatMessage
        except ImportError:
            self._raise_import_error(
                package_name="mistralai",
                package_min_version=MINIMUM_MISTRAL_VERSION,
            )
        self._client = MistralClient()
        self._async_client = MistralAsyncClient()
        self._ChatMessage = ChatMessage
        self._MistralAPIException = MistralAPIException

    def _init_rate_limiter(self) -> None:
        self._rate_limiter = RateLimiter(
            rate_limit_error=MistralRateLimitError,
            max_rate_limit_retries=10,
            initial_per_second_request_rate=self.initial_rate_limit,
            enforcement_window_minutes=1,
        )

    def invocation_parameters(self) -> Dict[str, Any]:
        params = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "random_seed": self.random_seed,
            "safe_mode": self.safe_mode,
            "safe_prompt": self.safe_prompt,
            "response_format": self.response_format,
        }
        # Mistral is strict about not passing None values to the API
        return {k: v for k, v in params.items() if v is not None}

    def _generate(self, prompt: Union[str, MultimodalPrompt], **kwargs: Dict[str, Any]) -> str:
        # instruction is an invalid input to Mistral models, it is passed in by
        # BaseEvalModel.__call__ and needs to be removed
        if isinstance(prompt, str):
            prompt = MultimodalPrompt.from_string(prompt)

        kwargs.pop("instruction", None)
        invocation_parameters = self.invocation_parameters()
        invocation_parameters.update(kwargs)
        response = self._rate_limited_completion(
            model=self.model,
            messages=self._format_prompt(prompt),
            **invocation_parameters,
        )

        return str(response)

    def _rate_limited_completion(self, **kwargs: Any) -> Any:
        @self._rate_limiter.limit
        def _completion(**kwargs: Any) -> Any:
            try:
                response = self._client.chat(**kwargs)
            except self._MistralAPIException as exc:
                http_status = getattr(exc, "http_status", None)
                if http_status and http_status == 429:
                    raise MistralRateLimitError() from exc
                raise exc
            return response.choices[0].message.content

        return _completion(**kwargs)

    async def _async_generate(
        self, prompt: Union[str, MultimodalPrompt], **kwargs: Dict[str, Any]
    ) -> str:
        # instruction is an invalid input to Mistral models, it is passed in by
        # BaseEvalModel.__call__ and needs to be removed
        if isinstance(prompt, str):
            prompt = MultimodalPrompt.from_string(prompt)

        kwargs.pop("instruction", None)
        invocation_parameters = self.invocation_parameters()
        invocation_parameters.update(kwargs)
        response = await self._async_rate_limited_completion(
            model=self.model,
            messages=self._format_prompt(prompt),
            **invocation_parameters,
        )

        return str(response)

    async def _async_rate_limited_completion(self, **kwargs: Any) -> Any:
        @self._rate_limiter.alimit
        async def _async_completion(**kwargs: Any) -> Any:
            try:
                response = await self._async_client.chat(**kwargs)
            except self._MistralAPIException as exc:
                http_status = getattr(exc, "http_status", None)
                if http_status and http_status == 429:
                    raise MistralRateLimitError() from exc
                raise exc

            return response.choices[0].message.content

        return await _async_completion(**kwargs)

    def _format_prompt(self, prompt: MultimodalPrompt) -> List["ChatMessage"]:
        ChatMessage = self._ChatMessage
        messages = []
        for part in prompt.parts:
            if part.content_type == PromptPartContentType.TEXT:
                messages.append(ChatMessage(role="user", content=part.content))
            else:
                raise ValueError(f"Unsupported content type: {part.content_type}")
        return messages
