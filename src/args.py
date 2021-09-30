args = ['ffmpeg', '-nostdin', '-err_detect', 'ignore_err', '-i', 'https://r1---sn-apqxgv-mf9e.googlevideo.com/videoplayback?expire=1632951399&ei=B4hUYYiiD9nDyQW3v6-QDQ&ip=95.140.185.11&id=o-AINHLqQtNPscQT5uJD7QDyP8eXadTJ8GfhqmQ78yB1Ta&itag=140&source=youtube&requiressl=yes&mh=WN&mm=31%2C29&mn=sn-apqxgv-mf9e%2Csn-5goeen7r&ms=au%2Crdu&mv=m&mvi=1&pl=20&gcr=se&initcwndbps=1855000&vprv=1&mime=audio%2Fmp4&ns=iKA09ImLCRP3qb2PbThlz-QG&gir=yes&clen=3086748&dur=190.682&lmt=1628139321602417&mt=1632929094&fvip=1&keepalive=yes&fexp=24001373%2C24007246&beids=24027534&c=WEB&txp=5532434&n=a9AFWLOeGX4duhW&sparams=expire%2Cei%2Cip%2Cid%2Citag%2Csource%2Crequiressl%2Cgcr%2Cvprv%2Cmime%2Cns%2Cgir%2Cclen%2Cdur%2Clmt&lsparams=mh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpl%2Cinitcwndbps&lsig=AG3C_xAwRAIga8yYbBiuBRUvLkHg8E7ruK4bH1x1_hfd-bYXt5nRIHECICQugy29AuWoQap1OQlNeKvBFBJ29OFmCZPfxlX7rD2h&sig=AOq0QJ8wRgIhAPeJkDLyt7j0arqRqVRZD9lCRFI71wD9vwjvm2poknAKAiEAy5C1-o0nOQ7HgBRP-yMaMCKEiAnB0ZFwqpjfHa3XdPY=&ratebypass=yes', '-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning', '-vn', '-sn', '-dn', '-ignore_unknown', 'output.mp3']

cmd = args[0]
for arg in args[1:]:
    cmd = cmd + ' ' + arg
print(cmd)

cmdList = list(cmd)
for i in range(0, len(cmdList)):
    if cmdList[i] == '&':
        cmdList[i] = '^'

cmdFixed = ''

for c in cmdList:
    cmdFixed = cmdFixed + c

print(cmdFixed)

"""Random garbage"""
