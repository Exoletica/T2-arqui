from logs_service.db import init_log_db


if __name__ == "__main__":
    init_log_db()
    print("Base de visitas inicializada (tabla visits).")
