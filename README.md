# Pollshow
A twitter bot to render polls for third party twitter clients

Depends on a wkhtmltoimage installation to work.

You need a `secret.properties` file to make it work:
```
[Main]
wkhtmltoimage = path to wkhtmltoimage
sleep_seconds = 10
sleep_between_tweets = 5
app_secret = 'your app secret'
app_key = 'your app key'

```
