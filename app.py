import os
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

def get_warrants_by_stock(stock_id):
    # 這裡未來可串接證交所 API 或爬蟲抓取真實權證資料
    # 目前先以範例格式回傳
    call_warrants = ['0%s01P (購)' % stock_id, '0%s02P (購)' % stock_id]
    put_warrants = ['0%s51R (售)' % stock_id]
    
    result = f"【{stock_id} 權證查詢結果】\n\n🟢 【認購 (購)】\n"
    result += "\n".join(call_warrants) if call_warrants else "無資料"
    result += "\n\n🔴 【認售 (售)】\n"
    result += "\n".join(put_warrants) if put_warrants else "無資料"
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

        # 判斷是否為 4 位數股票代號
        if user_text.isdigit() and len(user_text) == 4:
            reply_text = get_warrants_by_stock(user_text)
        else:
            reply_text = "請輸入正確的 4 位數股票代號（例如：2330）"

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

if __name__ == '__main__':
    app.run(port=5000)
