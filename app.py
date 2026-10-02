import os
import requests
from datetime import datetime
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET')

if channel_access_token is None or channel_secret is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET environment variables.')
    SystemExit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

# 儲存每個使用者的追蹤清單
user_watchlist = {}  # 格式: {user_id: ['2330', '7711']}

def get_stock_quote(symbol):
    sym = symbol.strip().upper()
    worker_url = f"https://twse-proxy.yijhuang8931.workers.dev?sym={sym}"
    try:
        res = requests.get(worker_url, timeout=4)
        if res.status_code != 200:
            return None
        data = res.json()
        meta = None
        if data.get('quoteResponse') and data['quoteResponse'].get('result'):
            meta = data['quoteResponse']['result'][0]
        elif data.get('chart') and data['chart'].get('result'):
            meta = data['chart'].get('result')[0].get('meta', {})
            
        if not meta:
            return None
            
        name = meta.get('shortName') or meta.get('symbol') or sym
        current_price = meta.get('regularMarketClose') or meta.get('regularMarketPrice') or meta.get('previousClose', 0)
        prev_close = meta.get('regularMarketPreviousClose') or meta.get('previousClose', current_price)
        diff = current_price - prev_close
        diff_percent = (diff / prev_close * 100) if prev_close > 0 else 0
        
        return {
            'symbol': sym,
            'name': name,
            'current_price': current_price,
            'prev_close': prev_close,
            'diff': diff,
            'diff_percent': diff_percent
        }
    except Exception as e:
        print(f"Error fetching quote: {e}")
        return None

# 定時推播任務 (每日 13:30 執行)
def job_daily_closing_report():
    print("⏰ 觸發每日 13:30 收盤回報任務...")
    if not user_watchlist:
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        for user_id, symbols in user_watchlist.items():
            if not symbols:
                continue
            
            report_lines = ["📊 【每日 13:30 收盤行情報告】\n"]
            for sym in symbols:
                quote = get_stock_quote(sym)
                if quote:
                    diff_sign = "+" if quote['diff'] > 0 else ""
                    report_lines.append(
                        f"• {quote['name']} ({sym})\n"
                        f"  收盤價: {quote['current_price']:.2f} | 漲跌: {diff_sign}{quote['diff']:.2f} ({diff_sign}{quote['diff_percent']:.2f}%)\n"
                    )
                else:
                    report_lines.append(f"• 股票代號 {sym} 暫時無法取得收盤價\n")
            
            push_text = "\n".join(report_lines)
            try:
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=push_text)]
                    )
                )
            except Exception as e:
                print(f"推播失敗給 {user_id}: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(job_daily_closing_report, 'cron', hour=13, minute=30, timezone='Asia/Taipei')
scheduler.start()

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id if event.source else 'default'
    user_text = event.message.text.strip()
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 幫助指令
        if user_text in ["幫助", "help", "使用說明"]:
            help_text = (
                "📖 【機器人使用說明】\n\n"
                "1️⃣ **查詢即時股價**：直接輸入 4 位數代號（例如 `2330` 或 `7711`）。\n"
                "2️⃣ **每日收盤追蹤**：\n"
                "   • 輸入 `追蹤2330` 加入清單\n"
                "   • 輸入 `我的追蹤` 查看清單\n"
                "   • 輸入 `取消追蹤2330` 移除\n"
                "   (系統將於每個交易日 13:30 自動推播收盤價)\n"
            )
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=help_text)]))
            return

        # 追蹤指令
        if user_text.startswith("追蹤"):
            sym = user_text.replace("追蹤", "").strip()
            if sym.isdigit() and len(sym) == 4:
                if user_id not in user_watchlist:
                    user_watchlist[user_id] = []
                if sym not in user_watchlist[user_id]:
                    user_watchlist[user_id].append(sym)
                reply_text = f"✅ 已成功將 【{sym}】 加入每日 13:30 收盤追蹤清單！目前清單：{user_watchlist[user_id]}"
            else:
                reply_text = "格式錯誤，請輸入如「追蹤2330」"
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))
            return

        if user_text.startswith("取消追蹤"):
            sym = user_text.replace("取消追蹤", "").strip()
            if user_id in user_watchlist and sym in user_watchlist[user_id]:
                user_watchlist[user_id].remove(sym)
                reply_text = f"🗑️ 已從追蹤清單移除 【{sym}】。"
            else:
                reply_text = f"清單中找不到代號 【{sym}】。"
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))
            return

        if user_text == "我的追蹤":
            list_syms = user_watchlist.get(user_id, [])
            reply_text = f"📋 您目前追蹤的股票清單：\n{', '.join(list_syms) if list_syms else '目前無追蹤股票'}"
            line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))
            return

        # 一般 4 位數股票代號查詢
        if user_text.isdigit() and len(user_text) == 4:
            quote = get_stock_quote(user_text)
            if quote:
                diff_sign = "+" if quote['diff'] > 0 else ""
                reply_text = (
                    f"📈 {quote['name']} ({quote['symbol']})\n"
                    f"現價：{quote['current_price']:.2f}\n"
                    f"漲跌：{diff_sign}{quote['diff']:.2f} ({diff_sign}{quote['diff_percent']:.2f}%)"
                )
            else:
                reply_text = f"找不到代號 【{user_text}】 的資料。"
        else:
            reply_text = "請輸入 4 位數股票代號（例如 2330），或輸入「幫助」查看使用說明！"

        line_bot_api.reply_message_with_http_info(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))

if __name__ == '__main__':
    app.run(port=5000)
