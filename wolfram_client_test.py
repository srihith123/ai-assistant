from wolframclient.evaluation import SecuredAuthenticationKey, WolframCloudSession, WolframLanguageSession
from wolframclient.language import wl, wlexpr

sak = SecuredAuthenticationKey(
    '',
    '')

session = WolframCloudSession(credentials=sak)
session.start()

print(session.authorized())

derivative = session.evaluate(wlexpr('D[E^x, x]'))
print(derivative)

session.terminate()