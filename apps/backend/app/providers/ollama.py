from decimal import Decimal

import httpx

from app.providers.base import Completion, LLMRequest, ProviderError, ProviderHealth

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class OllamaAdapter:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        num_ctx: int = 8192,
        timeout_s: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._num_ctx = num_ctx
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> ProviderHealth:
        try:
            response = await self._client.get("/api/tags", timeout=2.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name, available=False, model=self.model, detail=str(exc) or "error"
            )
        installed = {m.get("name") for m in response.json().get("models", [])}
        if self.model not in installed:
            return ProviderHealth(
                provider=self.name,
                available=False,
                model=self.model,
                detail=f"model not installed (run: ollama pull {self.model})",
            )
        return ProviderHealth(provider=self.name, available=True, model=self.model)

    async def complete(self, request: LLMRequest) -> Completion:
        body: dict[str, object] = {
            "model": self.model,
            "messages": [m.model_dump() for m in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
                "num_ctx": self._num_ctx,
            },
        }
        if request.json_schema is not None:
            body["format"] = request.json_schema

        try:
            response = await self._client.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"timeout: {exc}", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"connection error: {exc}", retryable=True) from exc

        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                retryable=response.status_code in _RETRYABLE_STATUS,
            )

        data = response.json()
        return Completion(
            content=data.get("message", {}).get("content", ""),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            est_cost_usd=Decimal(0),
        )
