# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from time import sleep
from typing import Any, TYPE_CHECKING

from flask import current_app
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver import chrome, firefox, FirefoxProfile
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from superset import feature_flag_manager
from superset.extensions import machine_auth_provider_factory
from superset.utils.retries import retry_call

WindowSize = tuple[int, int]
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from flask_appbuilder.security.sqla.models import User

if feature_flag_manager.is_feature_enabled("PLAYWRIGHT_REPORTS_AND_THUMBNAILS"):
    from playwright.sync_api import (
        BrowserContext,
        Error as PlaywrightError,
        Locator,
        Page,
        sync_playwright,
        TimeoutError as PlaywrightTimeout,
    )


class DashboardStandaloneMode(Enum):
    HIDE_NAV = 1
    HIDE_NAV_AND_TITLE = 2
    REPORT = 3


class ChartStandaloneMode(Enum):
    HIDE_NAV = "true"
    SHOW_NAV = 0


# pylint: disable=too-few-public-methods
class WebDriverProxy(ABC):
    def __init__(self, driver_type: str, window: WindowSize | None = None):
        self._driver_type = driver_type
        self._window: WindowSize = window or (800, 600)
        self._screenshot_locate_wait = current_app.config["SCREENSHOT_LOCATE_WAIT"]
        self._screenshot_load_wait = current_app.config["SCREENSHOT_LOAD_WAIT"]

    @abstractmethod
    def get_screenshot(self, url: str, element_name: str, user: User) -> bytes | None:
        """
        Run webdriver and return a screenshot
        """


class WebDriverPlaywright(WebDriverProxy):
    @staticmethod
    def auth(user: User, context: BrowserContext) -> BrowserContext:
        return machine_auth_provider_factory.instance.authenticate_browser_context(
            context, user
        )

    @staticmethod
    def find_unexpected_errors(page: Page) -> list[str]:
        error_messages = []

        try:
            alert_divs = page.get_by_role("alert").all()

            logger.debug(
                "%i alert elements have been found in the screenshot", len(alert_divs)
            )

            for alert_div in alert_divs:
                # See More button
                alert_div.get_by_role("button").click()

                # wait for modal to show up
                page.locator(".ant-modal-content").wait_for(state="visible")
                err_msg_div = page.locator(".ant-modal-content .ant-modal-body")
                #
                # # collect error message
                error_messages.append(err_msg_div.text_content())
                #
                # # Use HTML so that error messages are shown in the same style (color)
                error_as_html = err_msg_div.inner_html().replace("'", "\\'")
                #
                # # close modal after collecting error messages
                page.locator(".ant-modal-content .ant-modal-close").click()
                #
                # # wait until the modal becomes invisible
                page.locator(".ant-modal-content").wait_for(state="detached")
                try:
                    # Even if some errors can't be updated in the screenshot,
                    # keep all the errors in the server log and do not fail the loop
                    alert_div.evaluate(
                        "(node, error_html) => node.innerHtml = error_html",
                        [error_as_html],
                    )
                except PlaywrightError:
                    logger.exception("Failed to update error messages using alert_div")
        except PlaywrightError:
            logger.exception("Failed to capture unexpected errors")

        return error_messages

    def get_screenshot(  # pylint: disable=too-many-locals, too-many-statements
        self, url: str, element_name: str, user: User
    ) -> bytes | None:
        with sync_playwright() as playwright:
            browser_args = current_app.config["WEBDRIVER_OPTION_ARGS"]
            browser = playwright.chromium.launch(args=browser_args)
            pixel_density = current_app.config["WEBDRIVER_WINDOW"].get(
                "pixel_density", 1
            )
            context = browser.new_context(
                bypass_csp=True,
                viewport={
                    "height": self._window[1],
                    "width": self._window[0],
                },
                device_scale_factor=pixel_density,
            )
            context.set_default_timeout(
                current_app.config["SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT"]
            )
            self.auth(user, context)
            page = context.new_page()
            try:
                page.goto(
                    url,
                    wait_until=current_app.config["SCREENSHOT_PLAYWRIGHT_WAIT_EVENT"],
                )
            except PlaywrightTimeout:
                logger.exception(
                    "Web event %s not detected. Page %s might not have been fully loaded",
                    current_app.config["SCREENSHOT_PLAYWRIGHT_WAIT_EVENT"],
                    url,
                )

            img: bytes | None = None
            selenium_headstart = current_app.config["SCREENSHOT_SELENIUM_HEADSTART"]
            logger.debug("Sleeping for %i seconds", selenium_headstart)
            page.wait_for_timeout(selenium_headstart * 1000)
            element: Locator
            try:
                try:
                    # page didn't load
                    logger.debug(
                        "Wait for the presence of %s at url: %s", element_name, url
                    )
                    element = page.locator(f".{element_name}")
                    element.wait_for()
                except PlaywrightTimeout:
                    logger.exception("Timed out requesting url %s", url)
                    raise

                try:
                    # chart containers didn't render
                    logger.debug("Wait for chart containers to draw at url: %s", url)
                    slice_container_locator = page.locator(".chart-container")
                    slice_container_locator.first.wait_for()
                    for slice_container_elem in slice_container_locator.all():
                        slice_container_elem.wait_for()
                except PlaywrightTimeout:
                    logger.exception(
                        "Timed out waiting for chart containers to draw at url %s",
                        url,
                    )
                    raise
                try:
                    # charts took too long to load
                    logger.debug(
                        "Wait for loading element of charts to be gone at url: %s", url
                    )
                    for loading_element in page.locator(".loading").all():
                        loading_element.wait_for(state="detached")
                except PlaywrightTimeout:
                    logger.exception(
                        "Timed out waiting for charts to load at url %s", url
                    )
                    raise

                selenium_animation_wait = current_app.config[
                    "SCREENSHOT_SELENIUM_ANIMATION_WAIT"
                ]
                logger.debug(
                    "Wait %i seconds for chart animation", selenium_animation_wait
                )
                page.wait_for_timeout(selenium_animation_wait * 1000)

                # Dynamic height detection: remove CSS height constraints,
                # measure actual content height, and resize viewport to fit.
                if current_app.config.get("SCREENSHOT_DYNAMIC_HEIGHT", True):
                    try:
                        # Step 1: Remove height constraints so content
                        # flows naturally instead of being locked to 100vh
                        page.evaluate("""() => {
                            const selectors = [
                                'html', 'body',
                                '.standalone',
                                '.dashboard',
                                '.dashboard-content',
                                '.grid-container',
                                '.dashboard-grid',
                                '.react-grid-layout',
                            ];
                            for (const sel of selectors) {
                                const el = document.querySelector(sel);
                                if (el) {
                                    el.style.setProperty(
                                        'height', 'auto', 'important'
                                    );
                                    el.style.setProperty(
                                        'min-height', '0', 'important'
                                    );
                                    el.style.setProperty(
                                        'max-height', 'none', 'important'
                                    );
                                    el.style.setProperty(
                                        'overflow', 'visible', 'important'
                                    );
                                }
                            }
                        }""")
                        # Wait for the browser to reflow after CSS changes
                        page.wait_for_timeout(1000)

                        # Step 2: Measure actual content height
                        content_height = page.evaluate("""() => {
                            const grid = document.querySelector(
                                '.react-grid-layout'
                            );
                            if (grid) return grid.scrollHeight;
                            const standalone = document.querySelector(
                                '.standalone'
                            );
                            if (standalone) return standalone.scrollHeight;
                            return document.body.scrollHeight;
                        }""")
                        padding = current_app.config.get(
                            "SCREENSHOT_DYNAMIC_HEIGHT_PADDING", 100
                        )
                        max_height = current_app.config.get(
                            "SCREENSHOT_DYNAMIC_HEIGHT_MAX", 8000
                        )
                        target_height = min(
                            content_height + padding, max_height
                        )
                        logger.debug(
                            "Dynamic height: content=%d, target=%d (window=%d)",
                            content_height,
                            target_height,
                            self._window[1],
                        )

                        # Step 3: Resize viewport to fit content
                        page.set_viewport_size(
                            {"width": self._window[0], "height": target_height}
                        )
                        # Brief wait for reflow after resize
                        page.wait_for_timeout(500)
                    except Exception:  # pylint: disable=broad-except
                        logger.warning(
                            "Failed to detect dynamic height, "
                            "using static window size",
                            exc_info=True,
                        )

                logger.debug(
                    "Taking a PNG screenshot of url %s as user %s",
                    url,
                    user.username,
                )
                if current_app.config["SCREENSHOT_REPLACE_UNEXPECTED_ERRORS"]:
                    unexpected_errors = WebDriverPlaywright.find_unexpected_errors(page)
                    if unexpected_errors:
                        logger.warning(
                            "%i errors found in the screenshot. URL: %s. Errors are: %s",
                            len(unexpected_errors),
                            url,
                            unexpected_errors,
                        )
                img = element.screenshot()
            except PlaywrightTimeout:
                # raise again for the finally block, but handled above
                pass
            except PlaywrightError:
                logger.exception(
                    "Encountered an unexpected error when requesting url %s", url
                )
            return img


class WebDriverSelenium(WebDriverProxy):
    def create(self) -> WebDriver:
        pixel_density = current_app.config["WEBDRIVER_WINDOW"].get("pixel_density", 1)
        if self._driver_type == "firefox":
            driver_class = firefox.webdriver.WebDriver
            options = firefox.options.Options()
            profile = FirefoxProfile()
            profile.set_preference("layout.css.devPixelsPerPx", str(pixel_density))
            kwargs: dict[Any, Any] = {"options": options, "firefox_profile": profile}
        elif self._driver_type == "chrome":
            driver_class = chrome.webdriver.WebDriver
            options = chrome.options.Options()
            options.add_argument(f"--force-device-scale-factor={pixel_density}")
            options.add_argument(f"--window-size={self._window[0]},{self._window[1]}")
            kwargs = {"options": options}
        else:
            raise Exception(  # pylint: disable=broad-exception-raised
                f"Webdriver name ({self._driver_type}) not supported"
            )
        # Prepare args for the webdriver init

        # Add additional configured options
        for arg in current_app.config["WEBDRIVER_OPTION_ARGS"]:
            options.add_argument(arg)

        kwargs.update(current_app.config["WEBDRIVER_CONFIGURATION"])
        logger.debug("Init selenium driver")

        driver = driver_class(**kwargs)
        # Without this Selenium keeps its 300s default and a hung page only
        # fails after 5 minutes ("Timed out receiving message from renderer").
        page_load_timeout = current_app.config.get(
            "SCREENSHOT_SELENIUM_PAGE_LOAD_TIMEOUT"
        )
        if page_load_timeout:
            driver.set_page_load_timeout(page_load_timeout)
        return driver

    def auth(self, user: User) -> WebDriver:
        driver = self.create()
        return machine_auth_provider_factory.instance.authenticate_webdriver(
            driver, user
        )

    @staticmethod
    def destroy(driver: WebDriver, tries: int = 2) -> None:
        """Destroy a driver"""
        # This is some very flaky code in selenium. Hence the retries
        # and catch-all exceptions. quit() ends chromedriver and its Chrome
        # processes; close() first would wait on a hung renderer.
        try:
            retry_call(driver.quit, max_tries=tries)
        except Exception:  # pylint: disable=broad-except
            pass

    @staticmethod
    def find_unexpected_errors(driver: WebDriver) -> list[str]:
        error_messages = []

        try:
            alert_divs = driver.find_elements(By.XPATH, "//div[@role = 'alert']")
            logger.debug(
                "%i alert elements have been found in the screenshot", len(alert_divs)
            )

            for alert_div in alert_divs:
                # See More button
                alert_div.find_element(By.XPATH, ".//*[@role = 'button']").click()

                # wait for modal to show up
                modal = WebDriverWait(
                    driver,
                    current_app.config["SCREENSHOT_WAIT_FOR_ERROR_MODAL_VISIBLE"],
                ).until(
                    EC.visibility_of_any_elements_located(
                        (By.CLASS_NAME, "ant-modal-content")
                    )
                )[0]

                err_msg_div = modal.find_element(By.CLASS_NAME, "ant-modal-body")

                # collect error message
                error_messages.append(err_msg_div.text)

                # close modal after collecting error messages
                modal.find_element(By.CLASS_NAME, "ant-modal-close").click()

                # wait until the modal becomes invisible
                WebDriverWait(
                    driver,
                    current_app.config["SCREENSHOT_WAIT_FOR_ERROR_MODAL_INVISIBLE"],
                ).until(EC.invisibility_of_element(modal))

                # Use HTML so that error messages are shown in the same style (color)
                error_as_html = err_msg_div.get_attribute("innerHTML").replace(
                    "'", "\\'"
                )

                try:
                    # Even if some errors can't be updated in the screenshot,
                    # keep all the errors in the server log and do not fail the loop
                    driver.execute_script(
                        f"arguments[0].innerHTML = '{error_as_html}'", alert_div
                    )
                except WebDriverException:
                    logger.exception("Failed to update error messages using alert_div")
        except WebDriverException:
            logger.exception("Failed to capture unexpected errors")

        return error_messages

    def get_screenshot(self, url: str, element_name: str, user: User) -> bytes | None:
        """
        Take the screenshot, retrying with a fresh browser when the page fails
        to load (e.g. "Timed out receiving message from renderer" while several
        dashboards render at once). Waits after the page has loaded are not
        retried: they already allow minutes and a retry would double that.
        """
        retries = max(
            0, int(current_app.config.get("SCREENSHOT_SELENIUM_LOAD_RETRIES", 1))
        )
        for attempt in range(retries + 1):
            try:
                return self._get_screenshot_once(url, element_name, user)
            except WebDriverException:
                if attempt >= retries:
                    raise
                logger.warning(
                    "Page failed to load (attempt %i/%i), retrying with a new "
                    "browser: %s",
                    attempt + 1,
                    retries + 1,
                    url,
                    exc_info=True,
                )
        return None

    def _get_screenshot_once(
        self, url: str, element_name: str, user: User
    ) -> bytes | None:
        driver = self.create()
        try:
            # Inside try/finally: a page load timeout must still quit Chrome,
            # otherwise the hung browser stays in the worker and slows the
            # next reports down.
            driver = machine_auth_provider_factory.instance.authenticate_webdriver(
                driver, user
            )
            driver.set_window_size(*self._window)
            driver.get(url)
            return self._capture(driver, url, element_name, user)
        finally:
            self.destroy(driver, current_app.config["SCREENSHOT_SELENIUM_RETRIES"])

    def _capture(
        self, driver: WebDriver, url: str, element_name: str, user: User
    ) -> bytes | None:
        img: bytes | None = None
        selenium_headstart = current_app.config["SCREENSHOT_SELENIUM_HEADSTART"]
        logger.debug("Sleeping for %i seconds", selenium_headstart)
        sleep(selenium_headstart)

        try:
            try:
                # page didn't load
                logger.debug(
                    "Wait for the presence of %s at url: %s", element_name, url
                )
                element = WebDriverWait(driver, self._screenshot_locate_wait).until(
                    EC.presence_of_element_located((By.CLASS_NAME, element_name))
                )
            except TimeoutException:
                logger.exception("Selenium timed out requesting url %s", url)
                raise

            try:
                # chart containers didn't render
                logger.debug("Wait for chart containers to draw at url: %s", url)
                WebDriverWait(driver, self._screenshot_locate_wait).until(
                    EC.visibility_of_all_elements_located(
                        (By.CLASS_NAME, "chart-container")
                    )
                )
            except TimeoutException:
                logger.exception(
                    "Selenium timed out waiting for chart containers to draw at url %s",
                    url,
                )
                raise

            try:
                # charts took too long to load
                logger.debug(
                    "Wait for loading element of charts to be gone at url: %s", url
                )
                WebDriverWait(driver, self._screenshot_load_wait).until_not(
                    EC.presence_of_all_elements_located((By.CLASS_NAME, "loading"))
                )
            except TimeoutException:
                logger.exception(
                    "Selenium timed out waiting for charts to load at url %s", url
                )
                raise

            selenium_animation_wait = current_app.config[
                "SCREENSHOT_SELENIUM_ANIMATION_WAIT"
            ]
            logger.debug("Wait %i seconds for chart animation", selenium_animation_wait)
            sleep(selenium_animation_wait)

            # Dynamic height detection: remove CSS height constraints,
            # measure actual content height, and resize window to fit.
            if current_app.config.get("SCREENSHOT_DYNAMIC_HEIGHT", True):
                try:
                    # Step 1: Remove height constraints so content
                    # flows naturally instead of being locked to 100vh
                    driver.execute_script(
                        "var selectors = ["
                        "  'html', 'body',"
                        "  '.standalone',"
                        "  '.dashboard',"
                        "  '.dashboard-content',"
                        "  '.grid-container',"
                        "  '.dashboard-grid',"
                        "  '.react-grid-layout'"
                        "];"
                        "for (var i = 0; i < selectors.length; i++) {"
                        "  var el = document.querySelector(selectors[i]);"
                        "  if (el) {"
                        "    el.style.setProperty('height','auto','important');"
                        "    el.style.setProperty('min-height','0','important');"
                        "    el.style.setProperty('max-height','none','important');"
                        "    el.style.setProperty('overflow','visible','important');"
                        "  }"
                        "}"
                    )
                    # Wait for the browser to reflow after CSS changes
                    sleep(1)

                    # Step 2: Measure actual content height
                    content_height = driver.execute_script(
                        "var grid = document.querySelector('.react-grid-layout');"
                        " if (grid) return grid.scrollHeight;"
                        " var standalone = document.querySelector('.standalone');"
                        " if (standalone) return standalone.scrollHeight;"
                        " return document.body.scrollHeight;"
                    )
                    padding = current_app.config.get(
                        "SCREENSHOT_DYNAMIC_HEIGHT_PADDING", 100
                    )
                    max_height = current_app.config.get(
                        "SCREENSHOT_DYNAMIC_HEIGHT_MAX", 8000
                    )
                    target_height = min(
                        content_height + padding, max_height
                    )
                    logger.debug(
                        "Dynamic height: content=%d, target=%d (window=%d)",
                        content_height,
                        target_height,
                        self._window[1],
                    )

                    # Step 3: Resize window to fit content
                    driver.set_window_size(self._window[0], target_height)
                    # Brief wait for reflow after resize
                    sleep(0.5)
                except Exception:  # pylint: disable=broad-except
                    logger.warning(
                        "Failed to detect dynamic height, "
                        "using static window size",
                        exc_info=True,
                    )

            logger.debug(
                "Taking a PNG screenshot of url %s as user %s",
                url,
                user.username,
            )

            if current_app.config["SCREENSHOT_REPLACE_UNEXPECTED_ERRORS"]:
                unexpected_errors = WebDriverSelenium.find_unexpected_errors(driver)
                if unexpected_errors:
                    logger.warning(
                        "%i errors found in the screenshot. URL: %s. Errors are: %s",
                        len(unexpected_errors),
                        url,
                        unexpected_errors,
                    )

            img = element.screenshot_as_png
        except TimeoutException:
            # raise again for the finally block, but handled above
            pass
        except StaleElementReferenceException:
            logger.exception(
                "Selenium got a stale element while requesting url %s",
                url,
            )
        except WebDriverException:
            logger.exception(
                "Encountered an unexpected error when requesting url %s", url
            )
        return img
