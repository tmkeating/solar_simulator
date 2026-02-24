FROM python:3.10.13-slim  
  
WORKDIR /solar_simulation  
  
COPY ./Python_Script/linux_config.py .  
COPY ./Python_Script/pv_system_config.py .  
COPY ./Python_Script/influx_config.py .  
COPY ./Python_Script/main.py .  
  
RUN pip install --upgrade pip 
RUN pip install -r requirements.txt  
CMD [ "python3", "-u", "main.py" ] 