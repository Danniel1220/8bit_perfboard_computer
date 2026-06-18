#include <Arduino.h>

static byte reg_value = 0;

// bus mapping: bit i corresponds to index i
int in_pins[8]  = {15, 16, 17, 18, 19, 4, 3, 2};
int out_pins[8] = {12, 11, 10, 9, 8, 7, 6, 5};

int IE_PIN = 14;
int OE_PIN = 13;

bool aux = false;

void setup()
{
  for(int i = 0; i < 8; i++)
  {
    pinMode(in_pins[i], INPUT);
    pinMode(out_pins[i], OUTPUT);
  }
}

byte read_inputs() {
  byte value = 0;

  for (int i = 0; i < 8; i++) 
  {
    if (digitalRead(in_pins[i])) value |= (1 << i); // bit hack to read and move a bit in the correct place then OR-ing it to the value byte
  }

  return value;
}

void write_to_output(byte value) 
{
  for(int i = 0; i < 8; i++)
  {
    pinMode(out_pins[i], OUTPUT); // setting the pin as output
    digitalWrite(out_pins[i], (value >> i) & 1); // moving the current indexed bit to the LSB location and AND-ing with 1 to extract it, then writing the value
  }
}

void set_output_to_high_z()
{
  for(int i = 0; i < 8; i++)
  {
    pinMode(out_pins[i], INPUT);
  }
}

void write_value_to_register(byte value) 
{
  reg_value = value;
}

void loop()
{
  byte IE_PIN_VALUE = digitalRead(IE_PIN);
  byte OE_PIN_VALUE = digitalRead(OE_PIN);

  if(aux)
  {
    write_value_to_register(0b10101011);
    aux = !aux;
  }
  else
  {
    write_value_to_register(0b01010101);
    aux = !aux;
  }
  
  delay(200);

  if(IE_PIN_VALUE == 0) // IE is LOW active
  {
    reg_value = read_inputs();   
  }

  if(OE_PIN_VALUE == 0) // OE is LOW active
  {
    write_to_output(reg_value);
  }
  else
  {
    set_output_to_high_z();
  }
}