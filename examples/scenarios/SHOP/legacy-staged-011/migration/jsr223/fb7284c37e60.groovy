def t = props.get("sharedToken")
def sig = SignerUtil.hmac(t)
vars.put("authSig", sig)