"""docx-js 为每个 Bookmark 都写了 w:id="1"，导致 ID 冲突、Word/LibreOffice 无法打开。
这里按出现顺序重新编号（bookmarkStart 与其后紧邻的 bookmarkEnd 配对，无嵌套）。"""
import re
import shutil
import sys
import zipfile

src, dst = sys.argv[1], sys.argv[2]
shutil.copy(src, dst)

with zipfile.ZipFile(src) as z:
    names = z.namelist()
    data = {n: z.read(n) for n in names}

xml = data["word/document.xml"].decode("utf-8")

counter = [0]
stack = []


def repl(m):
    tag = m.group(1)
    name_attr = m.group(2)
    if tag == "bookmarkStart":
        counter[0] += 1
        stack.append(counter[0])
        new = counter[0]
    else:
        new = stack.pop() if stack else counter[0]
    return f'<w:{tag}{name_attr} w:id="{new}"'


xml = re.sub(r'<w:(bookmarkStart|bookmarkEnd)((?: w:name="[^"]*")?) w:id="\d+"', repl, xml)
data["word/document.xml"] = xml.encode("utf-8")

with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
    for n in names:
        z.writestr(n, data[n])

print(f"重编号书签 {counter[0]} 个 -> {dst}")
