import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from logging.config import dictConfig
from time import sleep

from colorama import Fore
from telethon import utils
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.types import ChannelParticipantsAdmins, PeerChannel

from config import config, log_config
from custom_features.safe_telegram_client import (
    SafeTelegramClient,
    make_telegram_client
)
from inviter_exceptions.exceptions import ContinueLoop
from opentele.tl import TelegramClient
from paths import FOLDER_NAMES, PATH
from utils import loginfo, move_account, withdrawal_of_rights_by_bot

dictConfig(log_config)
logger = logging.getLogger(__name__)

NOUSERNAME = "У аккаунта нет ника"
NO_FIRST_LAST_NAMES = "У аккаунта нет имени и фамилии"


class SuperAdminClient(ABC):
    def __init__(
        self,
        thread_index: str | int,
        threads_info: dict,
    ):
        self.thread_index: str | int = thread_index
        self.threads_info = threads_info
        self.client: TelegramClient
        self.username: str

    @abstractmethod
    def _initialize_client(self) -> bool:
        pass

    @abstractmethod
    def _start_client(self) -> bool:
        pass

    def run_client(self) -> bool:
        logger.debug(f"thread {self.thread_index}| pre _initialize_client")
        if self._initialize_client():
            logger.debug(f"thhread {self.thread_index}| pre _start_client")
            return self._start_client()
        logger.error(
            f"thread {self.thread_index}| error _initialize_client"
        )
        return False

    def get_username(self):
        return self.username if hasattr(self, "username") else NOUSERNAME

    def assign_as_admin(
        self,
        channel_id: int,
        username: str,
        admin_rights_dict: dict[str, bool]
    ):
        try:
            user_entity = self.client.get_entity(username)
            self.client.edit_admin(
                channel_id,
                user_entity,
                **admin_rights_dict
            )
            logger.debug(
                f"Assigned bot {username} as admin in {channel_id}"
            )
            return True
        except Exception as e:
            logger.error(
                "Error assigning bots as admins: "
                f"{type(e).__name__}: {e}"
            )
            return False


class BotSuperAdmin(SuperAdminClient):

    def __init__(self, bot_token: str, used_bot_tokens: dict, *args, **kwargs):
        self.token = bot_token
        self.used_bot_tokens = used_bot_tokens
        super().__init__(*args, **kwargs)

    def _initialize_client(self) -> bool:
        logger.debug(
            f"thread {self.thread_index}| SUPER_ADMIN_BOT_TOKEN: {self.token}"
        )
        if self.token in self.used_bot_tokens:
            logger.critical(
                f"thread {self.thread_index}| "
                f"ALARM bot_token already used: {self.token}"
            )
            return False
        self.used_bot_tokens[self.token] = True
        try:
            logger.debug(f"thread {self.thread_index}| Before bot_client")
            self.client = TelegramClient(
                PATH["dynamic_tmp_bot"](self.token),
                api_id=6,
                api_hash="eb06d4abfb49dc3eeb1aeb98ae0f581e",
                # loop=bot_loop,
            )
            logger.debug(f"thread {self.thread_index}| After bot_client")
        except Exception as e:
            logger.error(
                f"thread {self.thread_index}| create bot_client for bot: "
                f"{type(e).__name__}: {e}"
            )
            return False
        return True

    def _start_client(self) -> bool:
        try:
            self.client.start(bot_token=self.token)
            self.username = self.client.get_me().username
            logger.debug(f"{self.username} запущен.")
            return True
        except Exception as e:
            logger.error(
                f"thread {self.ADMIN_INDEX}| Ошибка запуска бота-суперадмина: "
                f"{type(e).__name__}: {e}"
            )
            return False


class UserSuperAdmin(SuperAdminClient):
    def __init__(self, phone: str, source_folder: str, *args, **kwargs):
        self.account = phone
        self.source_folder: str = source_folder
        self.destination_folder: str
        super().__init__(*args, **kwargs)
        self.client: SafeTelegramClient
        self.first_name: str
        self.last_name: str

    def _initialize_client(self) -> bool:
        if not self.account:
            logger.critical(
                f"thread {self.thread_index}| "
                "Не указан аккаунт user-суперадмина"
            )
            return False
        try:
            self.client = make_telegram_client(
                account=self.account,
                thread_index=self.thread_index,
                source_folder=self.source_folder
            )
            logger.debug(
                f"thread {self.thread_index}| After UserSuperAdmin.client"
            )
        except Exception as e:
            logger.error(
                f"thread {self.thread_index}| create UserSuperAdmin.client: "
                f"{type(e).__name__}: {e}"
            )
            return False
        logger.debug(
            f"thread {self.thread_index}| "
            "UserSuperAdmin Запускаем пользователя-суперадмина"
        )
        return True

    def _start_client(self) -> bool:
        try:
            if not self.connect_and_get_me():
                info_about_connect = (
                    f"{self.account} | "
                    "Аккаунт суперадмина из сессии, не подключён, "
                    "или уже запущен на другом ip."
                )
                loginfo(
                    self.thread_index,
                    info_about_connect,
                    self.threads_info
                )
                self.disconnect_move_account()
                logger.debug(
                    f"thread {self.thread_index}| "
                    "after disconnect_move_account."
                )
                return False
        except Exception as e:
            logger.error(
                f"thread {self.thread_index}| starting _client for user: "
                f"{type(e).__name__}: {e}"
            )
            return False
        info_about_connect = (
            f"{self.account} | "
            "Аккаунт пользователя суперадмина успешно подключён."
        )
        loginfo(
            self.thread_index,
            info_about_connect,
            self.threads_info,
            color=Fore.GREEN
        )
        return True

    def connect_and_get_me(self) -> bool:
        """
        Подключается к клиенту и получает информацию о текущем пользователе.
        """
        logger.debug(f"{self.account} | Start")
        try:
            self.client.connect()
            logger.debug(
                f"{self.account} | "
                f"Подключение"
            )
        except (*SafeTelegramClient.HANDLED_ERRORS, ContinueLoop) as e:
            logger.error(
                f"{self.account} | "
                f"Ошибка сессии: "
                f"{type(e).__name__}: {e}"
            )
            self.account_needs_moving = True
            self.destination_folder = FOLDER_NAMES["DEATH_FOLDER"]
            return False
        if self.chek_account():
            self.me = self.client.get_me()
            logger.debug(
                f"{self.account} | self.me: {self.me}"
            )
            self._get_name("first_name")
            self._get_name("last_name")
            self._get_name("username")
            logger.debug(
                f"thread {self.thread_index}| "
                f"Вошли как {self.get_username()=}"
            )
            return True
        else:
            logger.debug(
                f"{self.account} | "
                "Клиент не подключён| не залогинен"
            )
            self.account_needs_moving = True
            self.destination_folder = FOLDER_NAMES["DEATH_FOLDER"]
            return False

    def disconnect_move_account(self):
        self.client.disconnect()
        del self.client
        if self.account_needs_moving:
            move_account(
                self.source_folder,
                self.destination_folder,
                self.account,
                self.thread_index,
            )
        logger.debug(
            f"thread {self.thread_index}| "
            "after move_account."
        )

    def chek_account(self) -> bool:
        """
        Проверяет, авторизован ли пользователь в Telegram.

        Returns:
            bool: True если пользователь авторизован, False в противном случае.
        """
        if self.chek_is_connected():
            logger.debug(f"{self.account} | is_user_authorized?")
            return self.client.is_user_authorized()
        return False

    def chek_is_connected(self) -> bool:
        """
        Проверяет, подключен ли клиент к Telegram.

        Returns:
            bool: True если клиент подключен, False в противном случае.
        """
        try:
            is_connected = self.client.is_connected()
            logger.debug(
                f"{self.account} | "
                f"Клиент подключён? {is_connected}"
            )
        except ContinueLoop as e:
            logger.error(
                f"{self.account} | "
                f"Аккаунт вышел из сессии {e}"
            )
            is_connected = False
        return is_connected

    def invite_in_channel(
        self,
        username: str,
        channel_entity,
    ) -> bool:
        try:
            # Получение объекта бота по его имени пользователя
            bot_entity = self.client.get_entity(username)
            logger.debug("Получили сущность бота")

            # Приглашаем бота в канал
            self.client(InviteToChannelRequest(channel_entity, [bot_entity]))
            return True
        except Exception as e:
            logger.error(
                f"thread {self.thread_index}| Invite error: "
                f"{type(e).__name__}: {e}"
            )
            return False

    def _get_name(self, attribute: str):
        try:
            if hasattr(self.me, attribute):
                setattr(self, attribute, getattr(self.me, attribute))
                logger.debug(
                    f"thread {self.thread_index}| "
                    f"Fetched {attribute}: {getattr(self, attribute)}"
                )
            else:
                logger.warning(
                    f"Attribute '{attribute}' does not exist in 'self.me'."
                )
        except Exception as e:
            logger.error(
                f"thread {self.thread_index}| "
                f"Error fetching {attribute}: {type(e).__name__}: {e}"
            )

    def get_first_and_last_name(self) -> str:
        return (
            f"{self.first_name or ''} {self.last_name or ''}".strip()
            or NO_FIRST_LAST_NAMES
        )
