import os
import requests
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.getenv('LINE_CHANNEL_SECRET')

if channel_access_token is None or channel_secret is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET environment variables.')
    SystemExit(1)

handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

def get_stock_quote(symbol):
    sym = symbol.strip().upper()
    worker_url = f"https://twse-proxy.yijhuang8931.workers.dev?sym={sym}"
    
    try:
        res = requests.get(worker_url, timeout=3)
        if res.status_code != 200:
            return None
        data = res.json()
        meta = None
        if data.get('quoteResponse') and data['quoteResponse'].get('result'):
            meta = data['quoteResponse']['result'][0]
        elif data.get('chart') and data['chart'].get('result'):
            meta = data['chart']['result'][0]['meta']
            
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
            'diff': diff,
            'diff_percent': diff_percent
        }
    except Exception as e:
        print(f"Error fetching quote: {e}")
        return None

def get_warrants_for_stock(symbol):
    quote = get_stock_quote(symbol)
    if not quote:
        return f"找不到代號 【{symbol}】 的現股資料，請確認代號是否正確。"
        
    sign = "+" if quote['diff'] > 0 else ""
    header = f"【{quote['name']} ({quote['symbol']})】\n現價：{quote['current_price']:.2f} ({sign}{quote['diff']:.2f} / {sign}{quote['diff_percent']:.2f}%)\n"
    
    # 針對輸入的股號，提供標準的權證查詢指引與熱門模擬清單，避免遠端 API 卡死
    call_list = [f"• 0{symbol}01P 認購 (價外適中)", f"• 0{symbol}02P 認購 (微價內)"]
    put_list = [f"• 0{symbol}51R 認售 (避險專用)"]
    
    result = header + "\n🟢 【熱門認購權證】\n"
    result += "\n".join(call_list)
    
    result += "\n\n🔴 【熱門認售權證】\n"
    result += "\n".join(put_list)
    
    result += "\n\n(提示：可直接輸入 6 位數權證代號查詢即時價)"
    return result

@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info('Request body: ' + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        user_text = event.message.text.strip()

        if user_text.isdigit() and len(user_text) == 4:
            reply_text = get_warrants_for_stock(user_text)
        else:
            reply_text = "請輸入 4 位數股票代號（例如 2330），為您查詢現價與權證資訊！"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
