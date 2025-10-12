"""Module de retry avec backoff exponentiel pour opérations asynchrones.

Ce module fournit des décorateurs et utilitaires pour retry automatique
avec backoff exponentiel, utile pour gérer les erreurs transitoires
(timeouts DB, connexions réseau perdues, etc.).
"""

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def async_retry_with_backoff(
    max_attempts: int = 3,
    min_wait_seconds: int = 1,
    max_wait_seconds: int = 10,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Décorateur pour retry automatique avec backoff exponentiel (async).

    Args:
        max_attempts: Nombre maximum de tentatives (défaut: 3)
        min_wait_seconds: Attente minimale entre tentatives en secondes (défaut: 1)
        max_wait_seconds: Attente maximale entre tentatives en secondes (défaut: 10)
        exceptions: Tuple des exceptions qui déclenchent un retry

    Returns:
        Décorateur de fonction

    Example:
        ```python
        @async_retry_with_backoff(max_attempts=3, min_wait_seconds=2)
        async def sync_user(user_id: str):
            # Opération qui peut échouer temporairement
            await db.execute(query)
        ```
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return retry(
            retry=retry_if_exception_type(exceptions),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(
                min=min_wait_seconds,
                max=max_wait_seconds,
            ),
            before_sleep=_log_retry_attempt,
            reraise=True,
        )(func)

    return decorator


def _log_retry_attempt(retry_state: Any) -> None:
    """
    Logger les tentatives de retry pour observabilité.

    Args:
        retry_state: État de la tentative de retry
    """
    if retry_state.attempt_number > 1:
        exception = retry_state.outcome.exception()
        logger.warning(
            f"Retry attempt {retry_state.attempt_number} after {retry_state.seconds_since_start:.2f}s "
            f"for {retry_state.fn.__name__} - Exception: {exception}"
        )


async def retry_async_operation(
    operation: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    min_wait_seconds: int = 1,
    max_wait_seconds: int = 10,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """
    Exécute une opération async avec retry et backoff exponentiel.

    Alternative fonctionnelle au décorateur pour retry dynamique.

    Args:
        operation: Fonction async à exécuter
        *args: Arguments positionnels pour operation
        max_attempts: Nombre maximum de tentatives
        min_wait_seconds: Attente minimale entre tentatives (secondes)
        max_wait_seconds: Attente maximale entre tentatives (secondes)
        exceptions: Tuple des exceptions qui déclenchent un retry
        **kwargs: Arguments keyword pour operation

    Returns:
        Résultat de l'opération

    Raises:
        RetryError: Si toutes les tentatives échouent

    Example:
        ```python
        result = await retry_async_operation(
            sync_patient,
            patient_id=123,
            max_attempts=5,
            min_wait_seconds=2
        )
        ```
    """
    attempt = 0

    async for attempt_state in AsyncRetrying(
        retry=retry_if_exception_type(exceptions),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(min=min_wait_seconds, max=max_wait_seconds),
        reraise=True,
    ):
        with attempt_state:
            attempt += 1
            if attempt > 1:
                logger.info(f"Retry attempt {attempt}/{max_attempts} for {operation.__name__}")

            result = await operation(*args, **kwargs)
            return result

    # Ce code n'est jamais atteint (reraise=True lève l'exception)
    # mais est nécessaire pour la vérification de type
    raise RetryError("Max retries exceeded")
