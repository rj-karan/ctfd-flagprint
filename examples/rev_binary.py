"""Script delivery example: compile a small crackme per team, with the flag XOR-encoded inside.

Upload this as generate.py and set the download name to crackme. No input file is needed.
Needs gcc, which the flagprint/generator sandbox image includes.
"""
import os
import random
import subprocess

flag = os.environ["FLAG"].encode()
key = random.randrange(1, 256)
encoded = ", ".join(str(byte ^ key) for byte in flag)

source = f"""
#include <stdio.h>
#include <string.h>

static const unsigned char secret[] = {{{encoded}}};

int main(void) {{
    char input[128];
    printf("Password: ");
    if (!fgets(input, sizeof input, stdin)) return 1;
    input[strcspn(input, "\\n")] = 0;
    if (strlen(input) != sizeof secret) {{ puts("Nope."); return 1; }}
    for (size_t i = 0; i < sizeof secret; i++)
        if ((unsigned char)(input[i] ^ {key}) != secret[i]) {{ puts("Nope."); return 1; }}
    puts("Correct! Submit the password as the flag.");
    return 0;
}}
"""

with open("/tmp/crackme.c", "w") as handle:
    handle.write(source)
output = os.path.join(os.environ["OUTPUT_DIR"], os.environ["OUTPUT_NAME"] or "crackme")
subprocess.run(["gcc", "-O1", "-s", "-o", output, "/tmp/crackme.c"], check=True)
