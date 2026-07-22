# CAN log decoder

Запуск:

```powershell
py "can to user\main.py"
```

Скрипт просит выбрать один или несколько файлов `.csv`, `.xlsx`, `.xls` или `.xlsm`, затем JSON-шаблон из папки `templates` и путь для итогового Excel.

После выбора шаблона появляется окно со списком сигналов. По умолчанию галочки сняты: отметьте только нужные значения, чтобы не раздувать Excel-файл лишними колонками.

Поддерживаются два основных входных формата:

- новый CSV логгера: `CAN_ID_Hex`, `Data_Hex`, `Channel`, `Wall_Time`;
- старый формат регулятора, где в колонке `Data` первым байтом лежит PID, а последние 4 байта являются `float32`.

В итоговом `.xlsx` создаются листы:

- `data`: широкая таблица `TimeSec + сигналы`;
- `decoded_long`: подробные расшифрованные строки с источником, CAN ID, байтами и значением.

Без окон можно запустить так:

```powershell
py "can to user\main.py" "путь\к\can_messages.csv" -t "templates\gas_regulator.json" -s PV,SP,CV -o "decoded.xlsx"
```

Посмотреть имена сигналов шаблона:

```powershell
py "can to user\main.py" --list-signals -t "templates\gas_regulator.json"
```
