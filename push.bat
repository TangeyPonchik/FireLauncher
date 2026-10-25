@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo    FireLauncher - отправка на GitHub
echo ============================================
echo.

:: Проверка, что это git-репозиторий
if not exist ".git" (
    echo [ОШИБКА] Папка .git не найдена!
    echo Убедись, что ты находишься в корне git-репозитория.
    pause
    exit /b 1
)

:: Показываем, что изменилось
echo Измененные файлы:
git status --short
echo.

:: Спрашиваем сообщение коммита
set /p commit_msg="Введи сообщение коммита (Enter - отмена): "

if "%commit_msg%"=="" (
    echo Отмена. Коммит не создан.
    pause
    exit /b 0
)

echo.
echo [1/3] Добавляю файлы...
git add .

echo [2/3] Создаю коммит...
git commit -m "%commit_msg%"

:: Если коммит не удался (нечего коммитить) - это не ошибка, просто пропускаем
if errorlevel 1 (
    echo.
    echo [INFO] Нечего коммитить ^(все изменения уже сохранены^).
) else (
    echo [INFO] Коммит создан.
)

echo.
echo [3/3] Отправляю на GitHub...
git push

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось сделать push.
    echo Проверь интернет и доступ к репозиторию.
    pause
    exit /b 1
)

echo.
echo ============================================
echo    ГОТОВО! Изменения на GitHub.
echo ============================================
pause