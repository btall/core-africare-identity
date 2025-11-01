"""Module de retry avec backoff exponentiel pour opérations asynchrones.

Ce module fournit des décorateurs et utilitaires pour retry automatique
avec backoff exponentiel, utile pour gérer les erreurs transitoires
(timeouts DB, connexions réseau perdues, etc.).

Inclut également un Circuit Breaker pattern pour protéger contre les
cascades d'échecs et permettre une récupération gracieuse des services.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
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


class CircuitState(str, Enum):
    """États possibles du circuit breaker."""

    CLOSED = "closed"  # Circuit fermé, requêtes passent normalement
    OPEN = "open"  # Circuit ouvert, requêtes bloquées (fail-fast)
    HALF_OPEN = "half_open"  # Test de récupération en cours


class CircuitBreakerOpenError(Exception):
    """Exception levée lorsque le circuit breaker est ouvert."""

    def __init__(self, service_name: str):
        """
        Initialise l'exception CircuitBreakerOpenError.

        Args:
            service_name: Nom du service dont le circuit est ouvert
        """
        self.service_name = service_name
        super().__init__(
            f"Circuit breaker is OPEN for service '{service_name}'. "
            "Service is temporarily unavailable."
        )


class CircuitBreaker:
    """
    Implémentation du Circuit Breaker pattern pour résilience des services.

    Le circuit breaker protège contre les cascades d'échecs en coupant
    temporairement l'accès à un service défaillant, puis en testant
    périodiquement sa récupération.

    États du circuit:
    - CLOSED: Fonctionnement normal, toutes les requêtes passent
    - OPEN: Service indisponible, requêtes bloquées immédiatement (fail-fast)
    - HALF_OPEN: Test de récupération, requêtes limitées pour vérifier le service

    Attributes:
        name: Nom du service protégé (pour logging/metrics)
        failure_threshold: Nombre d'échecs consécutifs avant ouverture
        recovery_timeout: Durée (secondes) avant de tester la récupération
        success_threshold: Nombre de succès en HALF_OPEN pour fermer le circuit
        state: État actuel du circuit breaker
        failure_count: Compteur d'échecs consécutifs
        success_count: Compteur de succès consécutifs (en HALF_OPEN)
        last_failure_time: Timestamp du dernier échec

    Example:
        ```python
        cb = CircuitBreaker(
            name="keycloak-service",
            failure_threshold=5,
            recovery_timeout=60
        )

        async def get_user_roles(user_id: str):
            async def operation():
                return await keycloak.get_roles(user_id)
            return await cb.call(operation)
        ```
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ):
        """
        Initialise un circuit breaker.

        Args:
            name: Nom du service (pour logging et metrics)
            failure_threshold: Nombre d'échecs avant ouverture du circuit
            recovery_timeout: Secondes avant de tester la récupération
            success_threshold: Succès requis en HALF_OPEN pour fermer
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Retourne l'état actuel du circuit."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Retourne le compteur d'échecs."""
        return self._failure_count

    @property
    def success_count(self) -> int:
        """Retourne le compteur de succès (en HALF_OPEN)."""
        return self._success_count

    @property
    def last_failure_time(self) -> datetime | None:
        """Retourne le timestamp du dernier échec."""
        return self._last_failure_time

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Exécute une fonction à travers le circuit breaker.

        Args:
            func: Fonction async à exécuter
            *args: Arguments positionnels
            **kwargs: Arguments keyword

        Returns:
            Résultat de la fonction

        Raises:
            CircuitBreakerOpenError: Si le circuit est ouvert
            Exception: Exception originale si la fonction échoue
        """
        async with self._lock:
            # Vérifier si on peut tenter un reset
            if self._state == CircuitState.OPEN and self._should_attempt_reset():
                logger.info(f"Circuit breaker '{self.name}': Attempting recovery (HALF_OPEN)")
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

            # Bloquer immédiatement si OPEN
            if self._state == CircuitState.OPEN:
                logger.warning(f"Circuit breaker '{self.name}': Rejecting call (OPEN)")
                raise CircuitBreakerOpenError(self.name)

        # Exécuter la fonction
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Vérifie si assez de temps s'est écoulé pour tenter un reset."""
        if self._last_failure_time is None:
            return False

        elapsed = datetime.now() - self._last_failure_time
        return elapsed >= timedelta(seconds=self.recovery_timeout)

    async def _on_success(self) -> None:
        """Gère un succès d'appel."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.info(
                    f"Circuit breaker '{self.name}': Success in HALF_OPEN "
                    f"({self._success_count}/{self.success_threshold})"
                )

                if self._success_count >= self.success_threshold:
                    logger.info(f"Circuit breaker '{self.name}': Closing circuit (recovered)")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_failure_time = None

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success in CLOSED state
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """Gère un échec d'appel."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    f"Circuit breaker '{self.name}': Failure in HALF_OPEN, reopening circuit"
                )
                self._state = CircuitState.OPEN
                self._success_count = 0

            elif (
                self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold
            ):
                logger.error(
                    f"Circuit breaker '{self.name}': Opening circuit after "
                    f"{self._failure_count} failures"
                )
                self._state = CircuitState.OPEN


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
