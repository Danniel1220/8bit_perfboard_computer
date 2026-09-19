const int CLK_PULSE_REQ = 27;
const int HALT          = 26;
const int RUN_PROGRAM   = 25;
const int CLK           = 16;
const int SWITCH_STATE  = 18;
const int STEP_BUTTON   = 19;
const int POT           = 36;

void setup() {
  Serial.begin(115200);
  
  pinMode(CLK, OUTPUT);

  // external 10k pull-ups
  pinMode(CLK_PULSE_REQ, INPUT);
  pinMode(HALT, INPUT);
  pinMode(RUN_PROGRAM, INPUT);

  pinMode(SWITCH_STATE, INPUT);
  pinMode(STEP_BUTTON, INPUT);
}

void loop() {
  int clkRaw = digitalRead(CLK_PULSE_REQ);
  int haltRaw = digitalRead(HALT);
  int runRaw = digitalRead(RUN_PROGRAM);
  int switchRaw = digitalRead(SWITCH_STATE);
  int stepButtonRaw = digitalRead(STEP_BUTTON);
  int potRaw = analogRead(POT);

  // undo the ULN2803 inversion so these match the original 5V logic.
  int clk  = !clkRaw;
  int halt = !haltRaw;
  int run  = !runRaw;
  int stepButton  = !stepButtonRaw;

  Serial.print("CLK_PULSE_REQ: ");
  Serial.print(clk);

  Serial.print("   HALT: ");
  Serial.print(halt);

  Serial.print("   RUN/PROGRAM: ");
  Serial.print(run);

  Serial.print("   SWITCH: ");
  Serial.print(switchRaw);

  Serial.print("   STEP BUTTON: ");
  Serial.print(stepButton);

  Serial.print("   POT: ");
  Serial.println(potRaw);

  digitalWrite(16, HIGH);
  delay(200);
  digitalWrite(16, LOW);
  delay(200);

  
}