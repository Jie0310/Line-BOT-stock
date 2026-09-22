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
        res = requests.get(worker_url, timeout=5)
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
    
    warrant_api = "https://openapi.twse.com.tw/v1/exchangeReport/Twt48u_ALL"
    call_list = []
    put_list = []
    
    try:
        res = requests.get(warrant_api, timeout=6)
        if res.status_code == 200:
            items = res.json()
            for item in items:
                underlying = str(item.get('UnderlyingSecuritys', '') or item.get('Symbol', '') or item.get('标的代號', ''))
                w_code = item.get('WarrantCode', '') or item.get('權證代號', '')
                w_name = item.get('WarrantName', '') or item.get('權證名稱', '')
                w_type = item.get('CallPut', '') or item.get('購售', '')
                
                if symbol in underlying:
                    line_str = f"• {w_code} {w_name}"
                    if '購' in w_type or 'C' in w_type.upper():
                        if len(call_list) < 5:
                            call_list.append(line_str)
                    else:
                        if len(put_list) < 5:
                            put_list.append(line_str)
    except Exception as e:
        print(f"Warrant fetch error: {e}")
        
    result = header + "\n🟢 【熱門認購權證】\n"
    result += "\n".join(call_list) if call_list else "暫無符合的認購資料"
    
    result += "\n\n🔴 【熱門認售權證】\n"
    result += "\n".join(put_list) if put_list else "暫無符合的認售資料"
    
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
            reply_text = "請輸入 4 位數股票代號（例如 2330），為您列出對應的真實權證清單！"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
