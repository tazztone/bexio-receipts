import asyncio
import logging
from pathlib import Path
from typing import Optional

import structlog
from telegram import Update, Message
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler

from .pipeline import process_receipt
from .config import Settings
from .bexio_client import BexioClient

from .database import DuplicateDetector

logger = structlog.get_logger(__name__)

class ReceiptBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.download_dir = Path(settings.inbox_path) / "telegram"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_users = set(settings.telegram_allowed_users)
        self.db = DuplicateDetector(settings.database_path)

    def _is_allowed(self, user_id: int) -> bool:
        # Secure by default: if no users are allowed, deny all.
        if not self.allowed_users:
            logger.warning("TELEGRAM_ALLOWED_USERS is empty. Denying all access.")
            return False
        return user_id in self.allowed_users

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            await update.message.reply_text("Access denied. Your user ID: " + str(user_id))
            return
        await update.message.reply_text(
            "Welcome to bexio-receipts bot! 🧾🚀\n"
            "Send me a photo or a PDF of a receipt, and I'll process it for you."
        )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        doc = update.message.document
        if doc.mime_type not in ["image/png", "image/jpeg", "application/pdf"]:
            await update.message.reply_text("Unsupported file type. Please send PNG, JPG, or PDF.")
            return

        file = await context.bot.get_file(doc.file_id)
        file_path = self.download_dir / doc.file_name
        await file.download_to_drive(str(file_path))

        await self._trigger_processing(update.message, file_path)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        # Photo comes in different sizes, take the largest one
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        # Save as png/jpg based on what telegram provides (usually jpg)
        file_path = self.download_dir / f"receipt_{photo.file_id}.jpg"
        await file.download_to_drive(str(file_path))

        await self._trigger_processing(update.message, file_path)

    async def _trigger_processing(self, message: Message, file_path: Path):
        status_msg = await message.reply_text("Processing receipt... 🔄")
        
        async with BexioClient(
            token=self.settings.bexio_api_token, 
            base_url=self.settings.bexio_base_url
        ) as bexio:
            try:
                await bexio.cache_lookups()
                result = await process_receipt(str(file_path), self.settings, bexio, self.db)
                
                status = result.get("status")
                if status == "booked":
                    expense_id = result.get("expense_id")
                    merchant = result.get("receipt", {}).get("merchant_name", "Unknown")
                    total = result.get("receipt", {}).get("total_incl_vat", 0.0)
                    await status_msg.edit_text(
                        f"✅ Success! Expense {expense_id} booked in bexio.\n"
                        f"Merchant: {merchant}\n"
                        f"Total: {total} CHF"
                    )
                elif status == "review":
                    review_file = Path(result.get("review_file")).name
                    await status_msg.edit_text(
                        f"⚠️ Sent to review. Validation errors found.\n"
                        f"Visit the dashboard to approve."
                    )
                elif status == "duplicate":
                    await status_msg.edit_text(f"ℹ️ Duplicate detected. Already booked with ID: {result.get('expense_id')}")
                else:
                    await status_msg.edit_text(f"❌ Processing failed: {status}")
                    
            except Exception as e:
                logger.error(f"Telegram processing error: {e}")
                await status_msg.edit_text(f"❌ Error during processing: {str(e)}")

async def run_bot(settings: Settings):
    """Starts the Telegram bot."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set.")
        return

    bot = ReceiptBot(settings)
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    
    logger.info("Starting Telegram bot ingestion...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep the bot running
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
