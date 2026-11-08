Хостинг на Render (бесплатно)
1. Зайди на render.com, войди через GitHub.
2. Нажми New и выбери Web Service.
3. Выбери репозиторий MIET.
4. Runtime: Python 3. Build command: pip install -r requirements.txt
5. Start command: gunicorn wsgi:app
6. Deploy. Через минуту сайт поднимется, адрес вида https://miet.onrender.com
Замечание: на бесплатном тарифе база SQLite живет на временном диске и
сбрасывается при перезапуске. Для учебной сдачи это не критично.
