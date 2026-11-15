# app/utils/SnowflakeIDGenerator.py
import time
import threading
#主键获取

class SnowflakeIDGenerator:
    def __init__(self, datacenter_id: int, worker_id: int, epoch: int = 1700000000000):
        """
        :param datacenter_id: 数据中心 ID (0..31)
        :param worker_id:     工作节点 ID (0..31)
        :param epoch:         起始时间戳（毫秒）
        """
        self.sequence_bits = 12
        self.worker_id_bits = 5
        self.datacenter_id_bits = 5

        self.max_sequence = (1 << self.sequence_bits) - 1
        self.max_worker_id = (1 << self.worker_id_bits) - 1
        self.max_datacenter_id = (1 << self.datacenter_id_bits) - 1

        self.worker_id_shift = self.sequence_bits
        self.datacenter_id_shift = self.sequence_bits + self.worker_id_bits
        self.timestamp_shift = (self.sequence_bits + self.worker_id_bits + self.datacenter_id_bits)

        if not (0 <= datacenter_id <= self.max_datacenter_id):
            raise ValueError(f"datacenter_id must be 0..{self.max_datacenter_id}")
        if not (0 <= worker_id <= self.max_worker_id):
            raise ValueError(f"worker_id must be 0..{self.max_worker_id}")

        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.epoch = epoch

        self.sequence = 0
        self.last_timestamp = -1
        self._lock = threading.Lock()

    def _current_millis(self) -> int:
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_ts: int) -> int:
        ts = self._current_millis()
        while ts <= last_ts:
            ts = self._current_millis()
        return ts

    def next_id(self) -> int:
        with self._lock:
            timestamp = self._current_millis()
            if timestamp < self.last_timestamp:
                # 简单处理：等待时钟追上
                timestamp = self._wait_next_millis(self.last_timestamp)
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.max_sequence
                if self.sequence == 0:
                    timestamp = self._wait_next_millis(self.last_timestamp)
            else:
                self.sequence = 0
            self.last_timestamp = timestamp

            return ((timestamp - self.epoch) << self.timestamp_shift) | \
                   (self.datacenter_id << self.datacenter_id_shift) | \
                   (self.worker_id << self.worker_id_shift) | \
                   self.sequence

    def next_id_str(self) -> str:
        """返回字符串形式，避免前端 JS 精度丢失"""
        return str(self.next_id())


# 全局单例实例（datacenter_id=1, worker_id=1）
snowflake_id_generator = SnowflakeIDGenerator(datacenter_id=1, worker_id=1)


def get_snowflake_id() -> str:
    """模块级便捷函数：返回字符串形式的雪花 ID"""
    return snowflake_id_generator.next_id_str()