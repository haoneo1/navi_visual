# Makefile for vpr_simp_term

CC=g++
CFLAGS= -Wall -g -O2 -std=c++11
OBJ_FILES= main.o viper_queue.o viper_ui.o viper_usb.o 


all:vpr_simp_term

vpr_simp_term: $(OBJ_FILES)
	$(CC) $(CFLAGS) -o vpr_simp_term $(OBJ_FILES) -lusb-1.0 -lpthread 

main.o: main.cpp viper_ui.h viper_usb.h libusb.h ViperInterface.h
	$(CC) $(CFLAGS) -c main.cpp
viper_queue.o: viper_queue.cpp viper_queue.h
	$(CC) $(CFLAGS) -c viper_queue.cpp
viper_ui.o: viper_ui.cpp ViperInterface.h viper_usb.h libusb.h \
 viper_queue.h viper_ui.h
	$(CC) $(CFLAGS) -c viper_ui.cpp
viper_usb.o: viper_usb.cpp viper_usb.h libusb.h
	$(CC) $(CFLAGS) -c viper_usb.cpp


clean:
ifneq ("$(wildcard *.o)","") 
	@rm *.o
endif

ifneq ("$(wildcard *~)","")
	@rm *~
endif


