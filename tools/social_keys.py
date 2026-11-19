"""Read the social tokens from the key files in the Claude folder. Never prints them."""
import pathlib, re, zipfile
P = pathlib.Path(r'C:\Users\maxlo\OneDrive\Documents\2026\Personal\Projects\Claude')


def blob(name):
    with zipfile.ZipFile(P / name) as z:
        return b''.join(z.read(n) for n in z.namelist() if n.endswith('.iwa'))


def meta():
    txt = P / 'Meta-Token.txt'
    raw = txt.read_bytes() if txt.exists() else blob('Meta-Token.pages')
    found = sorted(set(re.findall(rb'(?:EA|IG)[A-Za-z0-9_-]{80,}', raw)), key=len, reverse=True)
    return [x.decode() for x in found]


def github():
    found = sorted(set(re.findall(rb'(?:github_pat_|ghp_)[A-Za-z0-9_]{30,}', blob('Git-Token.pages'))), key=len, reverse=True)
    return [x.decode() for x in found]


def claude():
    found = sorted(set(re.findall(rb'sk-ant-[A-Za-z0-9_-]{40,}', blob('Claude-Token.pages'))), key=len, reverse=True)
    return [x.decode() for x in found]
