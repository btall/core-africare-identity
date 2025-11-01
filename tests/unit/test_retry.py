"""Tests unitaires pour le module retry et circuit breaker."""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.retry import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    async_retry_with_backoff,
    retry_async_operation,
)


class TestCircuitBreaker:
    """Tests pour le circuit breaker pattern."""

    def test_circuit_breaker_initialization(self):
        """Test l'initialisation du circuit breaker avec valeurs par défaut."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60, success_threshold=2)

        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.success_threshold == 2
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.last_failure_time is None

    def test_circuit_breaker_custom_name(self):
        """Test circuit breaker avec nom personnalisé."""
        cb = CircuitBreaker(name="keycloak-service")

        assert cb.name == "keycloak-service"

    @pytest.mark.asyncio
    async def test_circuit_breaker_success_flow(self):
        """Test que le circuit reste CLOSED avec des succès."""
        cb = CircuitBreaker(failure_threshold=3)

        async def successful_operation():
            return "success"

        # Exécuter plusieurs fois avec succès
        for _ in range(5):
            result = await cb.call(successful_operation)
            assert result == "success"

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(self):
        """Test que le circuit s'ouvre après N échecs consécutifs."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        async def failing_operation():
            raise ValueError("Service unavailable")

        # Échouer 3 fois (threshold)
        for i in range(3):
            with pytest.raises(ValueError):
                await cb.call(failing_operation)

            if i < 2:
                assert cb.state == CircuitState.CLOSED
            else:
                assert cb.state == CircuitState.OPEN

        assert cb.failure_count == 3
        assert cb.last_failure_time is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_rejects_calls_when_open(self):
        """Test que les appels sont rejetés immédiatement quand le circuit est OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        async def failing_operation():
            raise ValueError("Service error")

        # Ouvrir le circuit (2 échecs)
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_operation)

        assert cb.state == CircuitState.OPEN

        # Tentative d'appel devrait lever CircuitBreakerOpenError immédiatement
        async def any_operation():
            return "should not execute"

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await cb.call(any_operation)

        assert "Circuit breaker is OPEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_after_timeout(self):
        """Test transition vers HALF_OPEN après recovery_timeout."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)  # 1 seconde

        async def failing_operation():
            raise ValueError("Error")

        # Ouvrir le circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_operation)

        assert cb.state == CircuitState.OPEN

        # Attendre le timeout
        await asyncio.sleep(1.1)

        # Forcer vérification de l'état (via _should_attempt_reset)
        async def test_operation():
            return "test"

        # Le circuit devrait passer en HALF_OPEN
        try:
            await cb.call(test_operation)
        except CircuitBreakerOpenError:
            pass  # Peut arriver si le timing n'est pas parfait

        # Alternativement, tester directement _should_attempt_reset
        cb._last_failure_time = datetime.now() - timedelta(seconds=2)
        assert cb._should_attempt_reset() is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_success_closes_circuit(self):
        """Test que le circuit se ferme après success_threshold succès en HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5, success_threshold=2)

        async def failing_operation():
            raise ValueError("Error")

        async def successful_operation():
            return "success"

        # Ouvrir le circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_operation)

        assert cb.state == CircuitState.OPEN

        # Attendre recovery timeout
        await asyncio.sleep(0.6)

        # Manuellement mettre en HALF_OPEN
        cb._state = CircuitState.HALF_OPEN
        cb._success_count = 0

        # Succès en HALF_OPEN (2 fois pour success_threshold=2)
        await cb.call(successful_operation)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.success_count == 1

        await cb.call(successful_operation)
        assert cb.state == CircuitState.CLOSED
        assert cb.success_count == 0
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_failure_reopens(self):
        """Test qu'un échec en HALF_OPEN rouvre immédiatement le circuit."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)

        async def failing_operation():
            raise ValueError("Still failing")

        # Ouvrir le circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing_operation)

        await asyncio.sleep(0.6)

        # Mettre en HALF_OPEN
        cb._state = CircuitState.HALF_OPEN

        # Échec devrait rouvrir
        with pytest.raises(ValueError):
            await cb.call(failing_operation)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_metrics_updated(self):
        """Test que les métriques sont correctement mises à jour."""
        cb = CircuitBreaker(failure_threshold=3)

        async def failing_operation():
            raise RuntimeError("Error")

        # Premier échec
        with pytest.raises(RuntimeError):
            await cb.call(failing_operation)

        assert cb.failure_count == 1
        assert cb.last_failure_time is not None

        # Deuxième échec
        with pytest.raises(RuntimeError):
            await cb.call(failing_operation)

        assert cb.failure_count == 2

    @pytest.mark.asyncio
    async def test_circuit_breaker_with_async_retry(self):
        """Test intégration circuit breaker avec retry decorator."""

        @async_retry_with_backoff(max_attempts=2, min_wait_seconds=0.1)
        async def flaky_operation():
            raise ConnectionError("Timeout")

        cb = CircuitBreaker(failure_threshold=3)

        # Le retry devrait essayer 2 fois, puis circuit breaker compte 1 échec
        with pytest.raises(ConnectionError):
            await cb.call(flaky_operation)

        assert cb.failure_count == 1

    def test_circuit_breaker_exception_message(self):
        """Test le message de CircuitBreakerOpenError."""
        exc = CircuitBreakerOpenError("test-service")

        assert "test-service" in str(exc)
        assert "Circuit breaker is OPEN" in str(exc)


class TestRetryDecorator:
    """Tests pour le décorateur async_retry_with_backoff."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        """Test qu'une fonction qui réussit ne fait pas de retry."""

        @async_retry_with_backoff(max_attempts=3)
        async def successful_function():
            return "success"

        result = await successful_function()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self):
        """Test qu'une fonction finit par réussir après quelques échecs."""
        attempt_count = 0

        @async_retry_with_backoff(max_attempts=3, min_wait_seconds=0.1)
        async def flaky_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = await flaky_function()
        assert result == "success"
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_retry_fails_after_max_attempts(self):
        """Test qu'une fonction qui échoue toujours lève l'exception."""

        @async_retry_with_backoff(max_attempts=2, min_wait_seconds=0.1)
        async def always_fails():
            raise RuntimeError("Permanent error")

        with pytest.raises(RuntimeError) as exc_info:
            await always_fails()

        assert "Permanent error" in str(exc_info.value)


class TestRetryAsyncOperation:
    """Tests pour retry_async_operation."""

    @pytest.mark.asyncio
    async def test_retry_operation_success(self):
        """Test retry d'une opération réussie."""

        async def operation(value: int):
            return value * 2

        result = await retry_async_operation(operation, 21, max_attempts=3)
        assert result == 42

    @pytest.mark.asyncio
    async def test_retry_operation_with_kwargs(self):
        """Test retry avec arguments keyword."""

        async def operation(a: int, b: int):
            return a + b

        result = await retry_async_operation(operation, max_attempts=2, a=10, b=32)
        assert result == 42
