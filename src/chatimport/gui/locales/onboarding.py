"""Strings of the API key guide and the first-run wizard (namespace `setup`)."""

# ruff: noqa: RUF001 - Cyrillic letters look like Latin ones, which is the point here
from __future__ import annotations

from typing import Final

from chatimport.gui.strings import register_strings

EN: Final[dict[str, str | tuple[str, ...]]] = {
    "guide.title": "How to get your Telegram API keys",
    "guide.lede": (
        "ChatImport reads your chats through your own Telegram account. Telegram gives every "
        "program its own free keys, api_id and api_hash. You create them once on Telegram's "
        "official site; it takes about two minutes."
    ),
    "guide.open": "Open my.telegram.org",
    "guide.step.1.title": "Open the Telegram developer site",
    "guide.step.1.body": "Go to my.telegram.org in any browser. The button below opens it.",
    "guide.step.2.title": "Enter your phone number",
    "guide.step.2.body": (
        "Type the number of your Telegram account in international format, starting with "
        "the country code, for example +598 99 123 456."
    ),
    "guide.step.3.title": "Enter the code from Telegram",
    "guide.step.3.body": (
        "The login code arrives inside the Telegram app on your phone, as a message from "
        "Telegram itself, not as an SMS. Type it on the site."
    ),
    "guide.step.4.title": 'Click "API development tools"',
    "guide.step.4.body": "It is in the list of options right after you log in.",
    "guide.step.5.title": "Fill in the form",
    "guide.step.5.body": (
        "App title: any text in Latin letters. Short name: 5 to 32 Latin letters or digits. "
        "Platform: Desktop. URL and Description may stay empty."
    ),
    "guide.step.6.title": 'Click "Create application"',
    "guide.step.6.body": "The site shows your application's page with the keys.",
    "guide.step.7.title": "Copy the two values into ChatImport",
    "guide.step.7.body": (
        "api_id is a number. api_hash is 32 characters: digits and the letters a to f. "
        "Paste both into the fields of the setup window or of Settings."
    ),
    "guide.trouble.title": 'The site shows "ERROR" when creating the application',
    "guide.trouble.body": (
        "This is a known quirk of my.telegram.org, and it is not caused by ChatImport. "
        "Try these in order:\n"
        "- Turn off a VPN or proxy and any ad blocker or privacy extension for this site.\n"
        "- Try another browser, or a private window.\n"
        "- Use Latin letters and digits only in every field, without spaces in Short name.\n"
        "- Wait an hour or a day and try again; the site sometimes rejects requests for a while."
    ),
    "guide.secret.title": "Keep api_hash secret",
    "guide.secret.body": (
        "Anyone who has your api_id and api_hash can act as an application on your account. "
        "Never send them to anyone, post them in a chat or put them in a screenshot. "
        "ChatImport stores them only in config.toml on this computer."
    ),
    "wizard.title": "Set up ChatImport",
    "wizard.step_of": "Step {n} of {total}",
    "wizard.back": "Back",
    "wizard.next": "Next",
    "wizard.skip": "Skip",
    "wizard.finish": "Finish",
    "step.keys": "API keys",
    "step.signin": "Sign in",
    "step.chats": "Chats",
    "step.folder": "Folder",
    "step.mode": "Run mode",
    "step.summary": "Summary",
    "keys.heading": "Telegram API keys",
    "keys.lede": (
        "ChatImport needs the api_id and api_hash of your Telegram application. "
        "They are stored only in config.toml on this computer."
    ),
    "keys.guide": "How do I get these keys?",
    "keys.error.write": "config.toml could not be written. Check that the file is not locked.",
    "keys.error.rejected": "These values were not accepted. Check them and try again.",
    "signin.heading": "Sign in to Telegram",
    "signin.lede": (
        "ChatImport signs in as one more device of your account. Telegram sends a code to "
        "your Telegram app. Nothing is ever sent or posted."
    ),
    "signin.done": "You are signed in. This step is complete.",
    "signin.needs_keys": "Save valid API keys in the first step before signing in.",
    "signin.button": "Sign in",
    "signin.signed_as": "Signed in as {handle}.",
    "chats.heading": "Chats to archive",
    "chats.lede": (
        "Paste links (t.me/name) or usernames (@name) of the groups and channels you belong "
        "to, one per line. You can add more later on the Chats page."
    ),
    "chats.known": (
        "{n} chat is already in the library.",
        "{n} chats are already in the library.",
    ),
    "chats.placeholder": "https://t.me/example\n@another_chat",
    "chats.add": "Add to library",
    "chats.empty": "Enter at least one link or username.",
    "chats.result.added": "Added",
    "chats.result.duplicate": "Already in the library",
    "chats.result.invalid": "Not a link or username",
    "chats.result.error": "Could not be added",
    "folder.heading": "Where to keep the archive",
    "folder.lede": (
        "The archive is plain files on this computer. The default folder is on your Desktop."
    ),
    "folder.path": "Archive folder",
    "folder.browse": "Browse...",
    "folder.pick": "Choose the archive folder",
    "folder.valid": "The archive will be kept in {path}.",
    "folder.invalid": "This folder cannot be used: {detail}",
    "folder.cloud": (
        "This folder is synced to the cloud (OneDrive). The archive holds sender names, and "
        "sync can lock or duplicate files. A folder outside OneDrive is safer."
    ),
    "folder.error.write": "config.toml could not be written. Check that the file is not locked.",
    "mode.heading": "How should ChatImport run?",
    "mode.lede": "You can change this later in Settings, under Startup.",
    "mode.auto": "Start with Windows and work in the background",
    "mode.auto_hint": "Recommended. The archive keeps filling without you opening anything.",
    "mode.manual": "Start manually from the desktop shortcut",
    "mode.manual_hint": "ChatImport collects messages only while you have it open.",
    "mode.unsupported": "Starting with the system is available only on Windows.",
    "summary.heading": "Ready to start",
    "summary.keys.ok": "API keys: saved",
    "summary.keys.missing": "API keys: not saved yet",
    "summary.signin.ok": "Telegram: signed in",
    "summary.signin.missing": "Telegram: not signed in yet",
    "summary.chats": "Chats in the library: {n}",
    "summary.folder": "Archive folder: {path}",
    "summary.mode.auto": "Run mode: starts with Windows",
    "summary.mode.manual": "Run mode: started manually",
    "summary.incomplete": (
        "Setup is not complete: the archive cannot start until the keys are saved and you "
        "are signed in. Use the button on the main window to continue later."
    ),
    "summary.finish_hint": "Finish saves your choices and starts the archive.",
    "finish.autostart_failed": "The autostart setting could not be changed. See Settings.",
    "about.rerun": "Run the setup wizard again",
    "about.rerun_hint": "Walk through the API keys, sign-in, chats, folder and run mode.",
}

RU: Final[dict[str, str | tuple[str, ...]]] = {
    "guide.title": "Как получить ключи Telegram API",
    "guide.lede": (
        "ChatImport читает ваши чаты через ваш собственный аккаунт Telegram. Для этого "
        "каждой программе нужны свои бесплатные ключи: api_id и api_hash. Их создают один "
        "раз на официальном сайте Telegram, это занимает около двух минут."
    ),
    "guide.open": "Открыть my.telegram.org",
    "guide.step.1.title": "Откройте сайт для разработчиков Telegram",
    "guide.step.1.body": "Зайдите на my.telegram.org в любом браузере. Кнопка ниже откроет сайт.",
    "guide.step.2.title": "Введите номер телефона",
    "guide.step.2.body": (
        "Введите номер вашего аккаунта Telegram в международном формате, начиная с кода "
        "страны, например +598 99 123 456."
    ),
    "guide.step.3.title": "Введите код из Telegram",
    "guide.step.3.body": (
        "Код входа приходит в приложение Telegram на телефоне, сообщением от самого "
        "Telegram, а не по SMS. Введите его на сайте."
    ),
    "guide.step.4.title": "Нажмите «API development tools»",
    "guide.step.4.body": "Этот пункт есть в списке сразу после входа.",
    "guide.step.5.title": "Заполните форму",
    "guide.step.5.body": (
        "App title: любой текст латиницей. Short name: от 5 до 32 латинских букв или цифр. "
        "Platform: Desktop. URL и Description можно оставить пустыми."
    ),
    "guide.step.6.title": "Нажмите «Create application»",
    "guide.step.6.body": "Сайт покажет страницу вашего приложения с ключами.",
    "guide.step.7.title": "Скопируйте два значения в ChatImport",
    "guide.step.7.body": (
        "api_id — это число. api_hash — 32 символа: цифры и буквы от a до f. "
        "Вставьте оба значения в поля окна настройки или раздела «Настройки»."
    ),
    "guide.trouble.title": "Сайт пишет «ERROR» при создании приложения",
    "guide.trouble.body": (
        "Это известная особенность my.telegram.org, ChatImport тут ни при чём. "
        "Попробуйте по порядку:\n"
        "- Отключите VPN, прокси и блокировщики рекламы для этого сайта.\n"
        "- Попробуйте другой браузер или приватное окно.\n"
        "- Во всех полях только латиница и цифры, в Short name без пробелов.\n"
        "- Подождите час или сутки и повторите: иногда сайт какое-то время отклоняет запросы."
    ),
    "guide.secret.title": "Храните api_hash в секрете",
    "guide.secret.body": (
        "Любой, у кого есть ваши api_id и api_hash, может действовать от имени приложения "
        "в вашем аккаунте. Никому не отправляйте их, не публикуйте в чатах и не оставляйте "
        "на скриншотах. ChatImport хранит их только в config.toml на этом компьютере."
    ),
    "wizard.title": "Настройка ChatImport",
    "wizard.step_of": "Шаг {n} из {total}",
    "wizard.back": "Назад",
    "wizard.next": "Далее",
    "wizard.skip": "Пропустить",
    "wizard.finish": "Готово",
    "step.keys": "Ключи API",
    "step.signin": "Вход",
    "step.chats": "Чаты",
    "step.folder": "Папка",
    "step.mode": "Запуск",
    "step.summary": "Итог",
    "keys.heading": "Ключи Telegram API",
    "keys.lede": (
        "ChatImport нужны api_id и api_hash вашего приложения Telegram. "
        "Они хранятся только в config.toml на этом компьютере."
    ),
    "keys.guide": "Как получить эти ключи?",
    "keys.error.write": "Не удалось записать config.toml. Проверьте, что файл не занят.",
    "keys.error.rejected": "Эти значения не приняты. Проверьте их и повторите.",
    "signin.heading": "Вход в Telegram",
    "signin.lede": (
        "ChatImport входит как ещё одно устройство вашего аккаунта. Telegram пришлёт код "
        "в приложение Telegram. Ничего не отправляется и не публикуется."
    ),
    "signin.done": "Вы вошли в аккаунт. Этот шаг выполнен.",
    "signin.needs_keys": "Сначала сохраните верные ключи API на первом шаге.",
    "signin.button": "Войти",
    "signin.signed_as": "Вход выполнен как {handle}.",
    "chats.heading": "Какие чаты сохранять",
    "chats.lede": (
        "Вставьте ссылки (t.me/имя) или имена (@имя) групп и каналов, в которых вы "
        "состоите, по одной в строке. Добавить ещё можно позже на странице «Чаты»."
    ),
    "chats.known": (
        "В библиотеке уже {n} чат.",
        "В библиотеке уже {n} чата.",
        "В библиотеке уже {n} чатов.",
    ),
    "chats.placeholder": "https://t.me/example\n@another_chat",
    "chats.add": "Добавить в библиотеку",
    "chats.empty": "Введите хотя бы одну ссылку или имя.",
    "chats.result.added": "Добавлен",
    "chats.result.duplicate": "Уже в библиотеке",
    "chats.result.invalid": "Это не ссылка и не имя",
    "chats.result.error": "Не удалось добавить",
    "folder.heading": "Где хранить архив",
    "folder.lede": (
        "Архив — это обычные файлы на этом компьютере. Папка по умолчанию лежит на рабочем столе."
    ),
    "folder.path": "Папка архива",
    "folder.browse": "Обзор...",
    "folder.pick": "Выберите папку архива",
    "folder.valid": "Архив будет храниться в {path}.",
    "folder.invalid": "Эту папку использовать нельзя: {detail}",
    "folder.cloud": (
        "Папка синхронизируется с облаком (OneDrive). В архиве есть имена отправителей, а "
        "синхронизация может блокировать или дублировать файлы. Лучше выбрать папку вне OneDrive."
    ),
    "folder.error.write": "Не удалось записать config.toml. Проверьте, что файл не занят.",
    "mode.heading": "Как запускать ChatImport?",
    "mode.lede": "Это можно изменить позже в настройках, в разделе «Запуск».",
    "mode.auto": "Запускать вместе с Windows и работать в фоне",
    "mode.auto_hint": "Рекомендуется. Архив пополняется, и ничего открывать не нужно.",
    "mode.manual": "Запускать вручную с ярлыка на рабочем столе",
    "mode.manual_hint": "ChatImport собирает сообщения, только пока открыт.",
    "mode.unsupported": "Запуск вместе с системой доступен только в Windows.",
    "summary.heading": "Всё готово к запуску",
    "summary.keys.ok": "Ключи API: сохранены",
    "summary.keys.missing": "Ключи API: ещё не сохранены",
    "summary.signin.ok": "Telegram: вход выполнен",
    "summary.signin.missing": "Telegram: вход ещё не выполнен",
    "summary.chats": "Чатов в библиотеке: {n}",
    "summary.folder": "Папка архива: {path}",
    "summary.mode.auto": "Запуск: вместе с Windows",
    "summary.mode.manual": "Запуск: вручную",
    "summary.incomplete": (
        "Настройка не закончена: архив не запустится, пока ключи не сохранены и вход не "
        "выполнен. Продолжить можно позже кнопкой в главном окне."
    ),
    "summary.finish_hint": "Кнопка «Готово» сохранит выбор и запустит архив.",
    "finish.autostart_failed": "Не удалось изменить автозапуск. Загляните в настройки.",
    "about.rerun": "Пройти мастер настройки заново",
    "about.rerun_hint": "Ключи API, вход, чаты, папка и режим запуска по шагам.",
}

register_strings("setup", EN, RU)
