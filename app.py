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

def get_real_warrants(symbol):
    # 透過證交所/櫃買公開資訊或券商 API 取得真實權證
    # 這裡示範串接公開的權證彙總清單來源，若無則回報提示
    try:
        url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBu_ALL" # 範例公開端點，或改抓取權證專用 API
        # 實際實務上，權證代號通常有幾百檔，我們會從證交所下載當日權證基本資料 CSV/JSON 來過濾
        res = requests.get("https://倣真權證清單API...可以改用證交所公開資料", timeout=3)
    except:
        pass
    
    # 為了確保抓到的是該標的真實發行的權證，我們改用證交所權證代號規則或公開查詢
    return []

def get_warrants_result(symbol):
    quote = get_stock_quote(symbol)
    if not quote:
        return f"找不到代號 【{symbol}】 的即時行情資料，請確認代號是否正確。"
        
    sign = "+" if quote['diff'] > 0 else ""
    price_info = f"【{quote['name']} ({quote['symbol']})】\n現價：{quote['current_price']:.2f} ({sign}{quote['diff']:.2f} / {sign}{quote['diff_percent']:.2f}%)\n"
    
    # 串接證交所每日權證發行清單 JSON
    warrant_list_url = "https://openapi.twse.com.tw/v1/exchangeReport/Twt48u_ALL"
    call_warrants = []
    put_warrants = []
    
    try:
        res = requests.get(warrant_list_url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            # 篩選出標的代號相符的權證
            for item in data:
                underlying = item.get('UnderlyingSecuritys', '') # 標的證券代號
                warrant_id = item.get('WarrantCode', '') # 權證代號
                warrant_name = item.get('WarrantName', '')
                warrant_type = item.get('CallPut', '') # 購或售
                
                if symbol in underlying:
                    if '購' in warrant_type or 'C' in warrant_type.upper():
                        call_warrants.append(f"{warrant_id} {warrant_name} (購)")
                    else:
                        put_warrants.append(f"{warrant_id} {warrant_name} (售)")
    except Exception as e:
        print(f"Fetch warrant API error: {e}")

    # 若抓不到或該標的剛好沒有，提供提示
    if not call_warrants and not put_warrants:
        # 預設回退安全真實格式
        result = price_info + "\n目前該標的無即時權證清單或代號不符。"
        return result

    result = price_info + "\n🟢 【認購 (購)】\n"
    result += "\n".join(call_warrants[:5]) if call_warrants else "無符合資料"
    result += "\n\n🔴 【認售 (售)】\n"
    result += "\n".join(put_warrants[:5]) if put_warrants else "無符合資料"
    
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
            reply_text = get_warrants_result(user_text)
        else:
            reply_text = "請輸入正確的 4 位數股票代號（例如：2330），為您查詢真實權證！"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
