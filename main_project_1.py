from machine import Pin, I2C, ADC
from ssd1306 import SSD1306_I2C
from fifo import Fifo
from filefifo import Filefifo
from piotimer import Piotimer

import urequests as requests
import network

import utime

import micropython
import gc

import mip
import network
from time import sleep
from umqtt.simple import MQTTClient
import ujson
import os

# Allocating a buffer for emergency exceptions with a size of 200 bytes
micropython.alloc_emergency_exception_buf(200)

class MQTT_sender:
    def __init__(self):
        self.SSID = "KMD751_Group4"
        self.PASSWORD = "Pass_Group4"
        self.BROKER_IP = "192.168.104.100"
    
    def send(self, message):
        self.connect_wlan()
        # Connect to MQTT
        try:
            mqtt_client=self.connect_mqtt()  
        except Exception as e:
            print(f"Failed to connect to MQTT: {e}")
        # Send MQTT message
        try:
            for _ in range(4):
            # Sending a message every 5 seconds.
                topic = "HRV analysis"
                mqtt_client.publish(topic, message)
                print(f"Sending to MQTT: {topic} -> {message}")
                sleep(5)
        except Exception as e:
                print(f"Failed to send MQTT message: {e}")
                       
    # Function to connect to WLAN
    def connect_wlan(self):
        # Connecting to the group WLAN
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.connect(self.SSID, self.PASSWORD)
        count_down = 5
        # Attempt to connect once per second
        while wlan.isconnected() == False and count_down > 0:
            print("Connecting... ")
            count_down -=1
            
        # Print the IP address of the Pico
        print("Connection successful. Pico IP:", wlan.ifconfig()[0])

    def connect_mqtt(self):
        mqtt_client=MQTTClient("group4", self.BROKER_IP)
        mqtt_client.connect(clean_session=True)
        return mqtt_client
    

class Adc:
    def __init__(self, adc_pin):
        self.adc = ADC(Pin(adc_pin, Pin.IN))
        self.adc_fifo = Fifo(size=5000, typecode='i')
        self.tmr = Piotimer(freq=250, callback=self.adc_callback)

    def adc_callback(self, tmr):
        self.adc_fifo.put(self.adc.read_u16())
        
    def cleanup(self):
        # Stop and deinitialize resources
        self.tmr.deinit()
    



class Heart_for_you:
    def __init__(self, horizontal_scale = 10, measurement_time_s = 30, frequency = 250, scale_koeff = 0.5, offset = 12):
    
        self.sample_number = 0
        self.horizontal_scale = horizontal_scale
        self.measurement_time_s = 30 # user's choice
        self.measurement_time = 0 # real measurement time
        self.frequency = frequency
        self.scale_koeff = scale_koeff
        self.offset = offset
        self.normalized_values = [0,0]
        self.r_peaks = [0]
        self.PPI = []
        self.filtered_PPI = []
        self.measurement_result = {}
        self.drop_first_PPI = 5
        
        
        #bpm calculating
        self.normalisation_window = 50

        self.max_bpm = 240
        self.min_bpm = 30

        self.peak_threshold = 0.60
        self.current_bpm = 0
        self.min_peaks_interval = 60 /self.max_bpm * (self.frequency / self.horizontal_scale)
         
#ADC
        self.adc_pin = 26
        self.hrm = Adc(self.adc_pin)
    
#KNOB    
        self.rotary_events = Fifo(50)
        self.C_LEFT = 10
        self.C_RIGHT = 11
        self.C_SWITCH = 12
        self.p1 = Pin(self.C_LEFT, Pin.IN)
        self.p2 = Pin(self.C_RIGHT, Pin.IN)
        self.p3 = Pin(self.C_SWITCH, Pin.IN, Pin.PULL_UP)

# interruption on ROTA
        self.p1.irq(self.rotate_handler, Pin.IRQ_FALLING)
        self.p3.irq(self.switch_handler, Pin.IRQ_FALLING)
    

   
# OLED I2C
        self.OLED_SDA = 14
        self.OLED_SCL = 15
        self.screen_width = 128
        self.screen_height = 64

# Initialize I2C to control the OLED
        self.i2c = I2C(1, scl=Pin(self.OLED_SCL), sda=Pin(self.OLED_SDA), freq=400000)
        self.oled = SSD1306_I2C(self.screen_width, self.screen_height, self.i2c)
        
#menu processing    
        self.menu_items = []
        self.selected_menu_item = 0
        
    
    def run(self):
        
        self.show_welcome_screen()        
        self.show_main_user_menu()
        
    def show_welcome_screen(self):
        self.oled.fill_rect(70, 0, 6, 34, 1)
        self.oled.fill_rect(55, 0, 6, 15, 1)
        self.oled.fill_rect(55, 12, 20, 4, 1)
        self.oled.text('HEART ', 25,22)
        self.oled.text('YOU ', 81,22)
        self.oled.show()
        
    def show_main_user_menu(self):
        self.menu_items = ['MEASURE', 'HISTORY']
        self.selected_menu_item = 0
        selected_item = self.select_menu_item()
        
        if selected_item == 'MEASURE':
            self.measurement_start()
        elif selected_item == 'HISTORY':
            self.history_menu()

    
    def formatted_date(self):
        current_time = utime.localtime()
        date = "{:02d}-{:02d}-{:02d} {:02d}:{:02d}".format(
        current_time[0] % 100, current_time[1], current_time[2], current_time[3], current_time[4])
        return date
        
    
    def hrv_analysis_menu(self):
        
        
        self.median_filter_PPI()      
        
        mean_PPI = int(max(1,sum(self.filtered_PPI)) / max(len(self.filtered_PPI), 1))
        
        #self.PPI.clear()
        
        mean_HR = int(60000 / mean_PPI)

        nn_intervals = [self.filtered_PPI[i + 1] - self.filtered_PPI[i] for i in range(len(self.filtered_PPI) - 1)]
        squared_diff = [diff ** 2 for diff in nn_intervals]
        mean_squared_diff = sum(squared_diff) / len(squared_diff)
        rmssd = int((mean_squared_diff) ** 0.5)
        del nn_intervals
        del squared_diff
        
        mean_nn_interval = sum(self.filtered_PPI) / len(self.filtered_PPI)
        squared_diff = [(nn_interval - mean_nn_interval) ** 2 for nn_interval in self.filtered_PPI]
        mean_squared_diff = sum(squared_diff) / len(squared_diff)
        sdnn = int((mean_squared_diff) ** 0.5)
        del mean_nn_interval
        del squared_diff
        
        date = self.formatted_date()
        
        
        self.measurement_result = {
             "mean_hr": mean_HR,
             "mean_ppi": mean_PPI,
             "rmssd": rmssd,
             "sdnn": sdnn,
             "date": date,
             "sns" : 0,
             "pns" : 0
        }
        print (self.measurement_result)
        self.show_measurement_result(menu_add = ['NEXT','SAVE','HOME'])
        
        
        
    def show_measurement_result(self, menu_add):    
        self.selected_menu_item = 0
        exit_loop = False
        print("smr self.measurement_result", self.measurement_result)
        while not exit_loop:
            
            self.menu_items = [self.measurement_result["date"]] + [f"{key} {value}" for key, value in self.measurement_result.items() if value != 0 and key != "date"] + menu_add
            
            selected_item = self.select_menu_item()
    
            if selected_item == 'HOME':
                self.clean_up()
                self.show_main_user_menu()
                exit_loop = True
            elif selected_item == 'NEXT':
                self.show_mqtt_kubious_menu()
                exit_loop = True
            elif selected_item == 'SAVE':
                self.save_response()
                self.show_main_user_menu()
                exit_loop = True
            elif selected_item == self.measurement_result["date"]:
                self.display_info_on_oled("date")
                sleep(1)
            else:
                key = selected_item.split(None, 1)[0]
                self.menu_items = [self.value_description(key, self.measurement_result[key])]
                self.selected_menu_item = 0
                self.select_menu_item()
        
   
    def value_description(self, term, value):
              
        ranges = {
            "mean_hr" : [(float('-inf'), 50, "LOW"), (50, 90, "NORMAL"), (90, float('+inf'), "HIGH")],
            "sdnn" : [(float('-inf'), 100, "UNHEALTHY"), (100, float('+inf'), "HEALTHY")],
            "rmssd" : [(float('-inf'), 19, "LOW"), (19, 107, "NORMAL"), (107, float('+inf'), "HIGH")],
            "sns" : [(float('-inf'), -1, "HIGH"), (-1, 1, "NORMAL"), (1, float('+inf'), "LOW")],
            "pns" : [(float('-inf'), -1, "LOW"), (-1, 1, "NORMAL"), (1, float('+inf'), "HIGH")],
            "mean_ppi" : [(float('-inf'), 667, "HIGH"), (667, 1200, "NORMAL"), (1200, float('+inf'), "LOW")]}
        
        for start, end, message in ranges[term]:
            if start <= value < end:
                return message
            
        return "not defined" 
            

    def show_mqtt_kubious_menu(self):
        self.selected_menu_item = 0
        self.menu_items = ['MQTT', 'KUBIOUS','HOME']
        selected_item = self.select_menu_item()
        
        if selected_item == 'MQTT':
            json_message = ujson.dumps(self.measurement_result)
            self.display_info_on_oled("mqtt sending...")
            mqtt = MQTT_sender()
            mqtt.send(json_message)
            self.show_mqtt_kubious_menu()
            
        elif selected_item == 'KUBIOUS':
            print(self.measurement_time)
            if self.measurement_time > 30 * 1000:
                
              self.kubious()
            else:
              self.display_info_on_oled("<30s no sending...")
              sleep(10)
              self.show_main_user_menu()
            
        elif selected_item == 'HOME':
            self.clean_up();
            self.show_main_user_menu()
            

              
    def kubious(self):
        dataset = {
             "type": "RRI",
             "data": self.filtered_PPI,
             "analysis": {"type": "readiness"}
        }
        try:
             # Connecting to the group WLAN
            
            #!!!!!!!!!!!!!!!!!!!!!!!!!!!
            wlan = network.WLAN(network.STA_IF)
            wlan.active(True)
            #wlan.connect("Koti_2951","GD34L8GHD4KYT")
            wlan.connect("KMD751_Group4","Pass_Group4")
            
            print("Connecting... ")
            message = "Connecting"
            # Attempt to connect once per second
            for _ in range(5):        
              message += "."
              self.display_info_on_oled(message)
            #utime.sleep(1) 
                
            # Print the IP address of the Pico
            print("Connection successful. Pico IP:", wlan.ifconfig()[0])
            self.display_info_on_oled("Sending...")
            #del self.filtered_PPI
            print(dataset)
            gc.collect()
            
            APIKEY = "pbZRUi49X48I56oL1Lq8y8NDjq6rPfzX3AQeNo3a"
            CLIENT_ID = "3pjgjdmamlj759te85icf0lucv"
            CLIENT_SECRET = "111fqsli1eo7mejcrlffbklvftcnfl4keoadrdv1o45vt9pndlef"
            LOGIN_URL = "https://kubioscloud.auth.eu-west-1.amazoncognito.com/login"
            TOKEN_URL = "https://kubioscloud.auth.eu-west-1.amazoncognito.com/oauth2/token"
            REDIRECT_URI = "https://analysis.kubioscloud.com/v1/portal/login"
            
            response = requests.post(
             url = TOKEN_URL,
             data = 'grant_type=client_credentials&client_id={}'.format(CLIENT_ID),
             headers = {'Content-Type':'application/x-www-form-urlencoded'},
             auth = (CLIENT_ID, CLIENT_SECRET))
            
            response = response.json() 
            access_token = response["access_token"] 
            
            
            response = requests.post(
             url = "https://analysis.kubioscloud.com/v2/analytics/analyze",
             headers = { "Authorization": "Bearer {}".format(access_token), #use access token to access your Kubios Cloud analysis session
             "X-Api-Key": APIKEY}, json = dataset) #dataset will be automatically converted to JSON by the urequests library
            response = response.json()
        
         
            
            mean_HR = int(response['analysis']['mean_hr_bpm'])
            mean_PPI = int(response['analysis']['mean_rr_ms'])
            rmssd = int(response['analysis']['rmssd_ms'])
            sdnn = int(response['analysis']['sdnn_ms'])
            sns = round(response['analysis']['sns_index'], 1)
            pns = round(response['analysis']['pns_index'], 1)

            date = self.formatted_date()
            
            self.measurement_result = {
                "date": date,
                "mean_hr": mean_HR,
                "mean_ppi": mean_PPI,
                "rmssd": rmssd,
                "sdnn": sdnn,
                "sns": sns,
                "pns": pns
            }
            
            self.show_measurement_result(menu_add = ['SAVE','HOME'])
            
        except Exception as e:
            print("Error connecting to Kubious:", e)        
            self.oled.fill(0)
            self.oled.text("No connection", 5, 10)
            self.oled.text("...", 5, 20)
            self.oled.show()
            sleep(3)
            self.show_main_user_menu()   
        
           
                
    def save_response(self):
         directory = 'hrv_analysis'
         try:
            os.mkdir(directory)
         except OSError as e:
            pass

         file_name = '{}/{}.txt'.format(directory, self.measurement_result["date"])
         print(file_name)

         files = [f for f in os.listdir(directory)]
         files.sort()

        
         while len(files) >= 5:
            file_to_remove = '{}/{}'.format(directory, files.pop(0))
            os.remove(file_to_remove)
    
         try:
            with open(file_name, "w", encoding="utf-8") as file:
                ujson.dump(self.measurement_result, file)
            self.oled.fill(0)
            self.oled.text("File saved ...", 5, 10)
            self.oled.show()
            sleep(3)   
         except Exception as e:
            print("Error saving response:", e)        
            self.oled.fill(0)
            self.oled.text("Error saving", 5, 10)
            self.oled.text("response...", 5, 20)
            self.oled.show()
            sleep(3)
            self.show_main_user_menu() 
                
 
        # Function to read the response from a file
    def read_response(self, file_name):
        try:
            with open(file_name, 'r') as file:
                content = file.read()
                self.measurement_result = ujson.loads(content)
            print("Response read successfully.")
            self.show_measurement_result(menu_add = ['HOME'])
        except Exception as e:
            print("File not found. No previous results available.")
            self.oled.fill(0)
            self.text("NOT FOUND", 10, 10, 1)
            self.oled.show()
            sleep(3)
            self.show_main_user_menu()
           
               
            
    def history_menu(self):
        directory = 'hrv_analysis'
        try:
            history_data = [f for f in os.listdir(directory)]
            history_data.sort()
        
            self.menu_items = [f"{filename}" for filename in history_data] + ['HOME']
            self.selected_item = 0 
            selected_item = self.select_menu_item()
            if selected_item == 'HOME':
                 self.clean_up()
                 self.show_main_user_menu()
            else:
                 file_path = '{}/{}'.format(directory, selected_item)
                 self.read_response(file_path)
                
        except Exception as e:
            print("No previous results available.")
            self.oled.fill(0)
            self.oled.text("NO HISTORY", 10, 10, 1)
            self.oled.show()
            sleep(3)
            self.show_main_user_menu()  

            
    def display_info_on_oled(self, info):
        self.oled.fill(0)
        self.oled.text(info, 10, 10, 1)
        self.oled.show()
        
    
    def median_filter_PPI(self):
        
        min_PPI = 60000 / self.max_bpm
        max_PPI = 60000 / self.min_bpm
        
        i = 0
        while i < len(self.PPI):
            if not (min_PPI <= self.PPI[i] <= max_PPI):
                del self.PPI[i]
            else:
                i += 1
        self.PPI = self.PPI[self.drop_first_PPI:]        
        gc.collect()
        
        #self.filtered_PPI = self.PPI
               
        median_filter_window = len(self.PPI) // 2 + 1 
          
        for i in range(len(self.PPI)):
            
            start_index = max(0, i - median_filter_window // 2)
            end_index = min(len(self.PPI), i + median_filter_window // 2 + 1)
            window = self.PPI[start_index:end_index]
            median_value = sorted(window)[len(window) // 2]
            self.filtered_PPI.append(median_value)
        
           
                             
# put_delay skips events if it comes too soon (ealier then 300 ms after previous one)                    
#events from KNOB
    def rotate_handler(self, pin):
         self.rotary_events.put_delay(self.p2.value())
        
    def switch_handler(self, pin):
         self.rotary_events.put_delay(3)
        

         
         

#clear events
#show time menu - 30s, 1min, 5min

    def measurement_start(self):
        time_mapping = {
            '30 sec': 30,
            '1 min': 60}
        self.menu_items = ['30 sec', '1 min']
        
        self.selected_menu_item = 0
        self.menu_items.append('HOME')
        
        selected_item = self.select_menu_item()
        if selected_item != 'HOME':
            self.selected_menu_item = 0
            self.measurement_time_s = time_mapping.get(selected_item)
            self.menu_items = ['...ready?']
            self.select_menu_item()
            self.measurement()
            self.hrv_analysis_menu()
        else:
            self.clean_up()
            self.show_main_user_menu()
            

    def measurement(self):
            min_value_ = 100000
            max_value_ = 0
            
            previous_bpm_time = 0 
            
            scale_min_value_ = 0
            scale_max_value_ = 1
            
            start_time = utime.ticks_ms()
            last_bpm_calculation_time = start_time
            
            stop_button_pressed = False
            self.clean_up()
            gc.collect()            

            while utime.ticks_diff(utime.ticks_ms(), start_time) < self.measurement_time_s * 1000 and not stop_button_pressed:
                
                scaled_sample = 0.0

                for _ in range(self.horizontal_scale):
                    if self.hrm.adc_fifo.has_data():
                          scaled_sample += self.hrm.adc_fifo.get()

                average_sample = float(scaled_sample / self.horizontal_scale)
                
                self.sample_number += 1
                
                
                if average_sample < min_value_:
                    min_value_ = average_sample
                if average_sample > max_value_:
                    max_value_ = average_sample

                if self.sample_number % self.normalisation_window == 0:
                    scale_min_value_ = min_value_
                    scale_max_value_ = max_value_
                    min_value_ = 100000
                    max_value_ = 1
                    
                if self.sample_number > self.normalisation_window:
                    
                    scale = max(1, scale_max_value_ - scale_min_value_)
                    normalized_value = max(0, min((average_sample - scale_min_value_) / (scale_max_value_ - scale_min_value_), 1))
                    gc.collect()
                    self.normalized_values.append(normalized_value)
                    self.draw()
                    
                    # checkif stop button pressed
                    if self.rotary_events.has_data():
                        if self.rotary_events.get() == 3:
                           stop_button_pressed = True
                           self.measurement_time = utime.ticks_diff(utime.ticks_ms(), start_time)
                           self.rotary_events.clear()
                           
                       
                    """
                    if utime.ticks_diff(utime.ticks_ms(), start_time) > 6000:
                            self.draw()
                    else:
                            self.oled.fill(0)
                            self.oled.text("...wait...", 10, 10, 1)
                            self.oled.text("...scaling...", 10, 20, 1)
                            self.oled.show()
                    """
                    current_gradient = self.normalized_values[-1] - self.normalized_values[-2]
                    previous_gradient = self.normalized_values[-2] - self.normalized_values[-3]

                    if current_gradient < 0 and previous_gradient >= 0:
                        current_peak = len(self.normalized_values) - 2
                            

                        # Check the minimum interval between peaks
                        min_peaks_interval_condition = current_peak - self.r_peaks[-1] > self.min_peaks_interval
                        last_rpeak_value = self.normalized_values[self.r_peaks[-1]]
                           
                         
                        peak_threshold_condition = self.normalized_values[current_peak] > (self.peak_threshold * last_rpeak_value)
                           
                        
                        if min_peaks_interval_condition and peak_threshold_condition:
                                self.r_peaks.append(current_peak)
                                self.calculate_bpm()
                                
                                       
            self.measurement_time = utime.ticks_diff(utime.ticks_ms(), start_time)
            self.hrm.adc_fifo.clear()
            
      
       
            
    def calculate_bpm(self):
        time_diff = float(self.r_peaks[-1] - self.r_peaks[-2]) / float((self.frequency / self.horizontal_scale)) 
        self.PPI.append(time_diff * 1000)
        self.current_bpm = int(60 / time_diff)
        

    def draw(self):
            
        previous_x = 0
        previous_y = self.screen_height // 2
            
        self.oled.fill(0)
        
        
        if (self.current_bpm > self.max_bpm or self.current_bpm < self.min_bpm):
            self.oled.text("...wait...", 10, 10, 1)
            self.oled.text("...scaling...", 10, 20, 1)
            self.oled.show()
        else:
            
            self.oled.text("BPM "+ str(self.current_bpm), self.screen_width //5, self.screen_height - 10)
                
            sample_x = 1
            
            

            for i in range(max(0, len(self.normalized_values) - 32), len(self.normalized_values), 1):
                point = self.normalized_values[i]
                sample_y = int((self.screen_height - point * self.screen_height) * self.scale_koeff) + self.offset
                sample_y = max(0, min(sample_y, self.screen_height))
                sample_x += 4


                # Draw a vertical line if the item is in r_peaks
                if i in self.r_peaks:
                    self.oled.line(sample_x + 4, 0, sample_x + 4, self.screen_height // 2, 1)

                self.oled.line(sample_x, previous_y, sample_x + 4, sample_y, 1)
                previous_y = sample_y

            # Show stop button
            stop_button_x = int(self.screen_width * 7 / 10)
            self.oled.fill_rect(stop_button_x, int(self.screen_height * 10 / 12) - 1, 40, 13, 1)
            self.oled.text("STOP", stop_button_x + 5, self.screen_height - 10, 0)

            self.oled.show()


        
        
         
    def print_PPI(self):
        gc.collect()
        #for i in range(len(self.PPI)):
        #     print(self.PPI[i])

    def clean_up(self):
        self.sample_number = 0
        self.normalized_values = [0,0]
        self.r_peaks = [0]
        self.PPI = []
        self.filtered_PPI = []
        self.measurement_result = {}
        self.selected_menu = 0
        
 
    def select_menu_item(self):
        self.rotary_events.clear()
        
        while True:
            self.oled.fill(0)
            display_start = max(0, self.selected_menu_item - 2)  # Adjust the range to show a few items above and below the selected one

            for i, item in enumerate(self.menu_items[display_start:display_start + 5]):
                y_position = (i + 1) * 15  # Offset to start from the second line
                if i + display_start == self.selected_menu_item:
                    self.oled.fill_rect(0, y_position-5, self.screen_width, 15,1)
                    
                    self.oled.text(item, 10, y_position, 0)

                else:
                    self.oled.text(item, 10, y_position, 1)
        
            self.oled.show()

            if self.rotary_events.has_data():
                event = self.rotary_events.get()
                
                if event == 3:  # button pressed
                    self.rotary_events.clear()
                    return self.menu_items[self.selected_menu_item]
                else:
                    if event == 1:
                        self.selected_menu_item = max(0, self.selected_menu_item - 1)
                    elif event == 0:
                        self.selected_menu_item = min(len(self.menu_items) - 1, self.selected_menu_item + 1)
                        
                        
                        


H4Y = Heart_for_you()
H4Y.run()


        




         
         
         
        




