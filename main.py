import os
import json
import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery

from google import genai
from google.genai import types as genai_types

# ==========================================
# 1. سيرفر HTTP وهمي لإرضاء Render ومنع إغلاق الخدمة
# ==========================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("MISTX Bot is running successfully!".encode('utf-8'))

    def log_message(self, format, *args):
        return  # إخفاء سجلات الـ HTTP لعدم ملء الـ Logs

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    print(f"==> Dummy HTTP Server running on port {port}")
    server.serve_forever()

# تشغيل السيرفر في خلفية (Thread)
threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# 2. إعداد المتغيرات الأساسية والعملاء
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://t.me/MISTX_Support")

logging.basicConfig(level=logging.INFO)

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("⚠️ الرجاء التأكد من ضبط TELEGRAM_TOKEN و GEMINI_API_KEY في متغيرات البيئة بـ Render!")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

# استخدام موديل Gemini الحديث والشغال بشكل سليم
MODEL_NAME = 'gemini-2.5-flash'

# قواعد البيانات المؤقتة في الذاكرة
promo_codes = {
    "MISTX100": 100,  # خصم 100%
    "MISTX50": 50,    # خصم 50%
    "MISTX20": 20     # خصم 20%
}
user_active_promo = {}  # {user_id: discount_percentage}
vip_users = set()        # قائمة الـ VIP
user_requests = {}      # حفظ الطلبات المعلقة {user_id: details}

SUPPORT_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
])

# ==========================================
# 3. الدوال المساعدة
# ==========================================

async def validate_and_apply_promo(code: str, message: types.Message):
    user_id = message.from_user.id
    discount = promo_codes.get(code)
    if discount:
        user_active_promo[user_id] = discount
        await message.answer(f"🎉 **تم تفعيل كود الخصم بنجاح!**\nحصلت على خصم بقيمة **{discount}%** على طلبك القادم.")
    else:
        await message.answer("❌ **كود الخصم غير صحيح أو منتهي الصلاحية.**")

async def generate_and_send_code(user_prompt: str, message: types.Message):
    """توليد الكود البرمجي وإرساله للعميل مباشرة"""
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await message.answer("⏳ **جاري كتابة وتوليد الكود البرمجي الخاص بك، يرجى الانتظار...**")
    
    system_instruction = (
        "أنت مهندس برمجيات خبير في متجر MISTX. قم بكتابة كود برمجي ممتاز، نظيف، "
        "وموثق بالكامل بناءً على طلب العميل، وأضف شرحاً مختصراً ل كيفية التشغيل."
    )
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        
        code_result = response.text
        
        # تقسيم الرسالة إذا كانت طويلة جداً
        if len(code_result) > 4000:
            for chunk in [code_result[i:i+4000] for i in range(0, len(code_result), 4000)]:
                await message.answer(chunk, parse_mode="Markdown")
        else:
            await message.answer(code_result, parse_mode="Markdown")
            
        await message.answer("✅ **تم تسليم الكود بنجاح!** شكراً لاستخدامك خدمات MISTX.")
    except Exception as e:
        logging.error(f"Error generating code: {e}")
        await message.answer(
            "⚠️ حدث خطأ أثناء توليد الكود. تواصل مع الدعم الفني للمساعدة.",
            reply_markup=SUPPORT_KEYBOARD
        )

# ==========================================
# 4. معالجة الأوامر والرسائل
# ==========================================

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    welcome_text = (
        f"أهلاً بك **{message.from_user.first_name}** في بوت الذكاء الفوري للأكواد **MISTX**! 🚀\n\n"
        "أنا مساعدك البرمجي الذكي. يمكنك إرسال أي طلب برمجي، سكربت، أو أداة ترغب في إنشائها وسأقوم بـ:\n"
        "1️⃣ تحليل الطلب فوراً.\n"
        "2️⃣ تقديم السعر التلقائي وطرق الدفع (PayPal / نجوم تلجرام).\n"
        "3️⃣ تسليم الكود البرمجي مباشرة عند إتمام الدفع!\n\n"
        "💡 *إذا كان لديك كود خصم، أرسله هنا قبل إرسال طلبك.*"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(F.text)
async def handle_chat_or_order(message: types.Message, state: FSMContext):
    user_text = message.text
    if not user_text:
        return
        
    user_id = message.from_user.id
    cleaned_input = user_text.strip().upper()

    # فحص كود الخصم
    if cleaned_input in promo_codes:
        await validate_and_apply_promo(cleaned_input, message)
        await state.clear()
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    try:
        # 1. فحص هل الطلب برمجي أم دردشة عادية
        analysis_prompt = (
            "حلل الرسالة التالية. هل يطلب العميل صراحة كتابة كود برمجي أو أداة أو سكربت أو حل مشكلة برمجية؟ "
            f"رسالة العميل: '{user_text}'\n"
            "رد بـ كلمة واحدة فقط 'YES' أو 'NO'."
        )
        check_res = client.models.generate_content(model=MODEL_NAME, contents=analysis_prompt)
        is_coding_request = "YES" in check_res.text.upper()
        
        if not is_coding_request:
            chat_prompt = f"أنت مستشار وخدمة عملاء لمتجر MISTX البرمجي. العميل يقول: {user_text}. أجب بلباقة واشرح كيف يمكنك مساعدته برمجياً."
            chat_response = client.models.generate_content(model=MODEL_NAME, contents=chat_prompt)
            await message.answer(chat_response.text)
            return

        discount = user_active_promo.get(user_id, 0)
        
        # فحص حالات الطلبات المجانية (VIP / Admin / خصم 100%)
        if user_id in vip_users or user_id == ADMIN_ID or discount == 100:
            if discount == 100:
                await message.answer("🎁 **تم تطبيق خصم 100%! طلبك مجاني بالكامل.**")
                user_active_promo.pop(user_id, None) 
            elif user_id != ADMIN_ID:
                await message.answer("🎁 **لديك اشتراك مجاني دائم (VIP)!**")
            
            await generate_and_send_code(user_text, message)
            return

        # 2. تحديد السعر تلقائياً عبر Gemini
        pricing_prompt = (
            f"حلل طلب العميل البرمجي التالي: '{user_text}'. "
            "حدد السعر المناسب بالدولار الأمريكي بناءً على تعقيد الطلب (من 3 إلى 50 دولار).\n"
            "رد بصيغة JSON حصرية فقط بدون أي نصوص أو markdown حولها:\n"
            '{"price_usd": 7, "details": "وصف قصير للسكربت", "time": "تسليم فوري"}'
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=pricing_prompt)
        
        raw_text = response.text.strip()
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}') + 1
        
        if start_idx != -1 and end_idx != 0:
            clean_json = raw_text[start_idx:end_idx]
            data = json.loads(clean_json)
        else:
            data = {"price_usd": 7, "details": "سكربت برمجي مخصص", "time": "تسليم فوري"}

        price_usd = int(data.get("price_usd", 7))
        price_stars = price_usd * 15  # المعادلة التقديرية للنجوم
        
        if discount > 0:
            price_usd = max(1, int(price_usd - (price_usd * discount / 100)))
            price_stars = max(15, int(price_stars - (price_stars * discount / 100)))
            discount_text = f"🎉 **تم تطبيق كود الخصم ({discount}%)!**\n"
        else:
            discount_text = ""
        
        details = data.get("details", "كود برمجي مخصص")
        
        user_requests[user_id] = {
            "prompt": user_text,
            "details": details,
            "price_usd": price_usd,
            "price_stars": price_stars
        }
        
        paypal_dynamic_link = f"https://paypal.me/DarkMail641/{price_usd}USD"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 دفع عبر PayPal ({price_usd}$)", url=paypal_dynamic_link)],
            [InlineKeyboardButton(text=f"⭐ دفع عبر نجوم تلجرام ({price_stars} نجمة)", callback_data=f"buy_stars_{price_stars}")],
            [InlineKeyboardButton(text="💬 التواصل مع الدعم الفني", url=SUPPORT_URL)]
        ])
        
        text_msg = (
            f"✅ **تم دراسة طلبك البرمجي!**\n\n"
            f"{discount_text}"
            f"📌 **التفاصيل:** {details}\n"
            f"💰 **التكلفة المطلوبة:** {price_usd}$ (أو {price_stars} نجمة تلجرام)\n\n"
            f"اختر وسيلة الدفع المناسبة بالأسفل للاستلام الفوري:"
        )
        
        await message.answer(text_msg, reply_markup=keyboard, parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"❌ Error processing request: {e}")
        await message.answer(
            "⚠️ **تعذر معالجة الطلب حالياً.**\nإذا واجهتك أي مشكلة، تواصل مباشرة مع الدعم الفني:",
            reply_markup=SUPPORT_KEYBOARD,
            parse_mode="Markdown"
        )

# ==========================================
# 5. معالجة دفع نجوم تلجرام (Telegram Stars)
# ==========================================

@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_payment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    req_data = user_requests.get(user_id)
    
    if not req_data:
        await callback.answer("⚠️ لم يتم العثور على طلب معلق. يرجى إرسال طلبك مجدداً.", show_alert=True)
        return
        
    price_stars = req_data["price_stars"]
    prices = [LabeledPrice(label=req_data["details"], amount=price_stars)]
    
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="طلب كود برمجي - MISTX",
        description=f"تسليم كود مخصص: {req_data['details']}",
        payload=f"stars_order_{user_id}",
        provider_token="",  # فارغ للدفع بالنجوم
        currency="XTR",
        prices=prices
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    req_data = user_requests.get(user_id)
    
    if req_data:
        prompt = req_data["prompt"]
        user_active_promo.pop(user_id, None)
        await message.answer("🎉 **تم استلام الدفع بنجاح!** جاري تحضير طلبك...")
        await generate_and_send_code(prompt, message)
    else:
        await message.answer("✅ تم استلام الدفع، شكرًا لك!")

# ==========================================
# 6. التشغيل الرئيسي
# ==========================================

async def main():
    print("🚀 جاري تشغيل بوت MISTX...")
    # إزالة أي Webhook قديم لتفادي التعارض
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
