# komunity
# To build the HIV+ Community development app
npx eas-cli build --platform android --profile preview-hiv

# To build the Diverse Hearts development app
npx eas-cli build --platform android --profile preview-general

adb tcpip 5555
adb connect 192.168.88.252
adb devices -1
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8000 tcp:8000 

client ID
f3e6f0b7-856e-40ae-95e8-5776055a3d52

client secret
lAnEWovFGugUCJE47xbVOgfFq7xLQ0l4

enc key
MLrd/OuB0vL3Mna0EFuFKqojpDjFW0grMZarkYfbmYE=

19203804939000

