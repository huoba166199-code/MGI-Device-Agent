import sqlite3
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 将原来的 DB_PATH 替换为：
DB_PATH = os.path.join(BASE_DIR, "data", "mgi_session.db")


def get_conn():
    """防御性获取数据库连接"""
    # 防御 1：确保父目录存在
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    # 防御 2：防止 Docker 把文件挂载成了“同名文件夹”
    if os.path.isdir(DB_PATH):
        raise IsADirectoryError(
            f"❌ 错误：{DB_PATH} 被 Docker 挂载成了文件夹！请删除宿主机上的同名文件夹，或者删掉 docker-compose 的 volumes 配置。")

    # 防御 3：增加 timeout 防止 WSL 跨文件系统锁死
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db():
    """初始化数据库表"""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS session
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY,
                     messages
                     TEXT,
                     awaiting_approval
                     INTEGER,
                     ticket_status
                     TEXT,
                     ticket_data
                     TEXT
                 )''')
    conn.commit()
    conn.close()


def load_session():
    """读取上次的状态"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT messages, awaiting_approval, ticket_status, ticket_data FROM session WHERE id = 1")
    row = c.fetchone()
    conn.close()

    if row:
        return {
            "messages": json.loads(row[0]) if row[0] else [],
            "awaiting_approval": bool(row[1]),
            "ticket_status": row[2],
            "ticket_data": json.loads(row[3]) if row[3] else {}
        }
    return None


def save_session(messages, awaiting_approval, ticket_status, ticket_data):
    """保存当前状态（防刷新丢失）"""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO session (id, messages, awaiting_approval, ticket_status, ticket_data)
                 VALUES (1, ?, ?, ?, ?)''',
              (json.dumps(messages, ensure_ascii=False),
               int(awaiting_approval),
               ticket_status,
               json.dumps(ticket_data, ensure_ascii=False)))
    conn.commit()
    conn.close()


def clear_session():
    """清空当前会话，用于重新开始"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM session WHERE id = 1")
    conn.commit()
    conn.close()