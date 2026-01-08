"""Concurrency Control Utilities (Optimized Version)

Performance improvements:
1. Dynamic concurrency limits (based on system load)
2. Separate concurrency control for different verification types
3. Support for higher concurrency
4. Load monitoring and automatic adjustment
"""
import asyncio
import logging
from typing import Dict
import psutil

logger = logging.getLogger(__name__)

# Dynamically calculate maximum concurrency
def _calculate_max_concurrency() -> int:
    """Calculate the maximum concurrency based on system resources"""
    try:
        cpu_count = psutil.cpu_count() or 4
        memory_gb = psutil.virtual_memory().total / (1024 ** 3)
        
        # Calculate based on CPU and memory
        # Each CPU core supports 3–5 concurrent tasks
        # Each GB of memory supports 2 concurrent tasks
        cpu_based = cpu_count * 4
        memory_based = int(memory_gb * 2)
        
        # Take the smaller value and apply upper/lower bounds
        max_concurrent = min(cpu_based, memory_based)
        max_concurrent = max(10, min(max_concurrent, 100))  # Between 10 and 100
        
        logger.info(
            f"System resources: CPU={cpu_count}, Memory={memory_gb:.1f}GB, "
            f"Calculated concurrency={max_concurrent}"
        )
        
        return max_concurrent
        
    except Exception as e:
        logger.warning(f"Unable to retrieve system resource info: {e}, using default value")
        return 20  # Default value

# Calculate base concurrency limit
_base_concurrency = _calculate_max_concurrency()

# Create independent semaphores for different verification types
# This prevents one verification type from blocking others
_verification_semaphores: Dict[str, asyncio.Semaphore] = {
    "gemini_one_pro": asyncio.Semaphore(_base_concurrency // 5),
    "chatgpt_teacher_k12": asyncio.Semaphore(_base_concurrency // 5),
    "spotify_student": asyncio.Semaphore(_base_concurrency // 5),
    "youtube_student": asyncio.Semaphore(_base_concurrency // 5),
    "bolt_teacher": asyncio.Semaphore(_base_concurrency // 5),
}


def get_verification_semaphore(verification_type: str) -> asyncio.Semaphore:
    """Get the semaphore for a specific verification type
    
    Args:
        verification_type: Verification type
        
    Returns:
        asyncio.Semaphore: Corresponding semaphore
    """
    semaphore = _verification_semaphores.get(verification_type)
    
    if semaphore is None:
        # Unknown type — create a default semaphore
        semaphore = asyncio.Semaphore(_base_concurrency // 3)
        _verification_semaphores[verification_type] = semaphore
        logger.info(
            f"Created semaphore for new verification type {verification_type}: "
            f"limit={_base_concurrency // 3}"
        )
    
    return semaphore


def get_concurrency_stats() -> Dict[str, Dict[str, int]]:
    """Get concurrency statistics
    
    Returns:
        dict: Concurrency information per verification type
    """
    stats = {}
    for vtype, semaphore in _verification_semaphores.items():
        # Note: _value is an internal attribute and may change across Python versions
        try:
            available = semaphore._value if hasattr(semaphore, '_value') else 0
            limit = _base_concurrency // 3
            in_use = limit - available
        except Exception:
            available = 0
            limit = _base_concurrency // 3
            in_use = 0
        
        stats[vtype] = {
            'limit': limit,
            'in_use': in_use,
            'available': available,
        }
    
    return stats


async def monitor_system_load() -> Dict[str, float]:
    """Monitor system load
    
    Returns:
        dict: System load information
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory_percent = psutil.virtual_memory().percent
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory_percent,
            'concurrency_limit': _base_concurrency,
        }
    except Exception as e:
        logger.error(f"Failed to monitor system load: {e}")
        return {
            'cpu_percent': 0.0,
            'memory_percent': 0.0,
            'concurrency_limit': _base_concurrency,
        }


def adjust_concurrency_limits(multiplier: float = 1.0):
    """Dynamically adjust concurrency limits
    
    Args:
        multiplier: Adjustment multiplier (0.5–2.0)
    """
    global _verification_semaphores, _base_concurrency
    
    # Clamp multiplier range
    multiplier = max(0.5, min(multiplier, 2.0))
    
    new_base = int(_base_concurrency * multiplier)
    new_limit = max(5, min(new_base // 3, 50))  # 5–50 per type
    
    logger.info(
        f"Adjusting concurrency limits: multiplier={multiplier}, "
        f"new_base={new_base}, per_type={new_limit}"
    )
    
    # Create new semaphores
    for vtype in _verification_semaphores.keys():
        _verification_semaphores[vtype] = asyncio.Semaphore(new_limit)


# Load monitoring task
_monitor_task = None

async def start_load_monitoring(interval: float = 60.0):
    """Start the load monitoring task
    
    Args:
        interval: Monitoring interval (seconds)
    """
    global _monitor_task
    
    if _monitor_task is not None:
        return
    
    async def monitor_loop():
        while True:
            try:
                await asyncio.sleep(interval)
                
                load_info = await monitor_system_load()
                cpu = load_info['cpu_percent']
                memory = load_info['memory_percent']
                
                logger.info(
                    f"System load: CPU={cpu:.1f}%, Memory={memory:.1f}%"
                )
                
                # Automatically adjust concurrency limits
                if cpu > 80 or memory > 85:
                    # Load too high — reduce concurrency
                    adjust_concurrency_limits(0.7)
                    logger.warning("System load is high, reducing concurrency limits")
                elif cpu < 40 and memory < 60:
                    # Load is low — increase concurrency
                    adjust_concurrency_limits(1.2)
                    logger.info("System load is low, increasing concurrency limits")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Load monitoring error: {e}")
    
    _monitor_task = asyncio.create_task(monitor_loop())
    logger.info(f"Load monitoring started: interval={interval}s")


async def stop_load_monitoring():
    """Stop the load monitoring task"""
    global _monitor_task
    
    if _monitor_task is not None:
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        _monitor_task = None
        logger.info("Load monitoring stopped")
