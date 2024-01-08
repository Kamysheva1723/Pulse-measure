import os        
        
        
directory = 'hrv_analysis'
try:
            os.mkdir(directory)
except OSError as e:
            pass

file_name = '{}/{}.txt'.format(directory, "date")
print(file_name)

        # Получение списка файлов в текущем каталоге
files = [f for f in os.listdir(directory)]
print(f"Files in {directory}: {files}")
        # Упорядочивание списка файлов по имени
files.sort()

        # Удаление старых файлов, чтобы осталось не более 5
while len(files) >= 5:
    file_to_remove = '{}/{}'.format(directory, files.pop(0))
    os.remove(file_to_remove)
    
try:
            with open(file_name, "w", encoding="utf-8") as file:
                ujson.dump(self.measurement_result, file)
except Exception as e:
            print("Error saving response:", e)

              