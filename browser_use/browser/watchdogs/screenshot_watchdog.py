"""Screenshot watchdog for handling screenshot requests using CDP."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.page import CaptureScreenshotParameters

from browser_use.browser.events import ScreenshotEvent
from browser_use.browser.views import BrowserError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	pass


class ScreenshotWatchdog(BaseWatchdog):
	"""Handles screenshot requests using CDP."""

	# Events this watchdog listens to
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [ScreenshotEvent]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	@observe_debug(ignore_input=True, ignore_output=True, name='screenshot_event_handler')
	async def on_ScreenshotEvent(self, event: ScreenshotEvent) -> str:
		"""Handle screenshot request using CDP.

		Args:
			event: ScreenshotEvent with optional full_page and clip parameters

		Returns:
			Dict with 'screenshot' key containing base64-encoded screenshot or None
		"""
		started_at = time.monotonic()
		self.logger.debug('[ScreenshotWatchdog] Handler START - on_ScreenshotEvent called')
		self.logger.info(
			'[ScreenshotWatchdog] ScreenshotEvent start: event_id=%s timeout=%s full_page=%s clip=%s focus_target=%s',
			event.event_id[-4:],
			event.event_timeout,
			event.full_page,
			bool(event.clip),
			self.browser_session.agent_focus_target_id[-4:] if self.browser_session.agent_focus_target_id else None,
		)
		try:
			# Validate focused target is a top-level page (not iframe/worker)
			# CDP Page.captureScreenshot only works on page/tab targets
			focused_target = self.browser_session.get_focused_target()
			self.logger.info(
				'[ScreenshotWatchdog] Focused target resolved: event_id=%s target_id=%s target_type=%s elapsed=%.2fs',
				event.event_id[-4:],
				focused_target.target_id[-4:] if focused_target and focused_target.target_id else None,
				focused_target.target_type if focused_target else None,
				time.monotonic() - started_at,
			)

			if focused_target and focused_target.target_type in ('page', 'tab'):
				target_id = focused_target.target_id
			else:
				# Focused target is iframe/worker/missing - fall back to any page target
				target_type_str = focused_target.target_type if focused_target else 'None'
				self.logger.warning(f'[ScreenshotWatchdog] Focused target is {target_type_str}, falling back to page target')
				page_targets = self.browser_session.get_page_targets()
				self.logger.info(
					'[ScreenshotWatchdog] Page-target fallback: event_id=%s page_targets=%d elapsed=%.2fs',
					event.event_id[-4:],
					len(page_targets),
					time.monotonic() - started_at,
				)
				if not page_targets:
					raise BrowserError('[ScreenshotWatchdog] No page targets available for screenshot')
				target_id = page_targets[-1].target_id

			cdp_started_at = time.monotonic()
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=True)
			self.logger.info(
				'[ScreenshotWatchdog] CDP session ready: event_id=%s target_id=%s session_id=%s elapsed=%.2fs total_elapsed=%.2fs',
				event.event_id[-4:],
				target_id[-4:] if target_id else None,
				cdp_session.session_id[-4:] if cdp_session.session_id else None,
				time.monotonic() - cdp_started_at,
				time.monotonic() - started_at,
			)

			# Prepare screenshot parameters
			params = CaptureScreenshotParameters(format='png', captureBeyondViewport=False)

			# Take screenshot using CDP
			self.logger.debug(f'[ScreenshotWatchdog] Taking screenshot with params: {params}')
			capture_started_at = time.monotonic()
			self.logger.info(
				'[ScreenshotWatchdog] Page.captureScreenshot begin: event_id=%s target_id=%s session_id=%s total_elapsed=%.2fs',
				event.event_id[-4:],
				target_id[-4:] if target_id else None,
				cdp_session.session_id[-4:] if cdp_session.session_id else None,
				time.monotonic() - started_at,
			)
			result = await cdp_session.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp_session.session_id)
			self.logger.info(
				'[ScreenshotWatchdog] Page.captureScreenshot complete: event_id=%s elapsed=%.2fs total_elapsed=%.2fs has_data=%s',
				event.event_id[-4:],
				time.monotonic() - capture_started_at,
				time.monotonic() - started_at,
				bool(result and 'data' in result),
			)

			# Return base64-encoded screenshot data
			if result and 'data' in result:
				self.logger.info(
					'[ScreenshotWatchdog] ScreenshotEvent complete: event_id=%s bytes=%d total_elapsed=%.2fs',
					event.event_id[-4:],
					len(result['data']),
					time.monotonic() - started_at,
				)
				self.logger.debug('[ScreenshotWatchdog] Screenshot captured successfully')
				return result['data']

			raise BrowserError('[ScreenshotWatchdog] Screenshot result missing data')
		except asyncio.CancelledError:
			self.logger.warning(
				'[ScreenshotWatchdog] ScreenshotEvent cancelled: event_id=%s elapsed=%.2fs',
				event.event_id[-4:],
				time.monotonic() - started_at,
			)
			raise
		except Exception as e:
			self.logger.error(
				'[ScreenshotWatchdog] ScreenshotEvent failed: event_id=%s elapsed=%.2fs error=%s: %s',
				event.event_id[-4:],
				time.monotonic() - started_at,
				type(e).__name__,
				e,
			)
			self.logger.error(f'[ScreenshotWatchdog] Screenshot failed: {e}')
			raise
		finally:
			# Try to remove highlights even on failure
			cleanup_started_at = time.monotonic()
			try:
				await self.browser_session.remove_highlights()
				self.logger.info(
					'[ScreenshotWatchdog] Highlight cleanup complete: event_id=%s elapsed=%.2fs total_elapsed=%.2fs',
					event.event_id[-4:],
					time.monotonic() - cleanup_started_at,
					time.monotonic() - started_at,
				)
			except Exception as exc:
				self.logger.debug(
					'[ScreenshotWatchdog] Highlight cleanup failed: event_id=%s elapsed=%.2fs error=%s: %s',
					event.event_id[-4:],
					time.monotonic() - cleanup_started_at,
					type(exc).__name__,
					exc,
				)
				pass
