import subprocess

from chatimport.autostart import _is_absent, task_command

r = subprocess.CompletedProcess(["schtasks"], 1, b"", "ОШИБКА: Отказано в доступе.".encode("cp866"))
print("Localized access denied classified absent:", _is_absent(r))
print("Packaged command:", task_command("C:/Applications/ChatImport.exe"))
