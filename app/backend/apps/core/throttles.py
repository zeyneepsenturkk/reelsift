from ninja.throttling import AnonRateThrottle


# Sayaç anahtarı kapsam + IP'dir; uçlar birbirinin sayacını tüketmesin diye her uca ayrı kapsam.
class LoginThrottle(AnonRateThrottle):
    scope = "login"


class ShareThrottle(AnonRateThrottle):
    scope = "share"
