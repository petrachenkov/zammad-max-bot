"""
Общие ресурсы для бота и webhook сервера
"""
import queue

# 🔥 Глобальная очередь сообщений (ОДИН экземпляр для всех)
message_queue = queue.Queue()