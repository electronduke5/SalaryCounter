import os
import tempfile

from cryptography.fernet import Fernet

# Импорт api выполняет migrate() + DataManager() с относительными путями
# (salary.db / salary_data.json), поэтому запуск pytest из корня репозитория
# трогал бы боевые файлы: создавал salary.db, а при его отсутствии — мигрировал
# и архивировал настоящий salary_data.json со случайным одноразовым ключом.
# Вся тестовая сессия работает из пустого временного каталога.
os.chdir(tempfile.mkdtemp(prefix="salarycounter-tests-"))

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
