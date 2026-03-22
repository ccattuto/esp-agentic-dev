/*
 * SPDX-FileCopyrightText: 2010-2022 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: CC0-1.0
 */

#include <stdio.h>
#include <inttypes.h>
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "SEGGER_RTT.h"
#include "esp_app_trace.h"
#include "esp_log.h"

void app_main(void)
{
	uint32_t counter = 0;

	esp_log_set_vprintf(esp_apptrace_vprintf);
 
    printf("Hello world! (stdout)\n");
	SEGGER_RTT_printf(0, "Hello world! (RTT)\n");
	ESP_LOGI("main", "Hello world! (app_trace)\n");

	while (1) {
        printf("counter = %ld\n", counter);
		SEGGER_RTT_printf(0, "counter = %ld\n", counter);
		ESP_LOGI("main", "counter = %ld\n", counter);
		esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, 1000);

        vTaskDelay(1000 / portTICK_PERIOD_MS);
		counter++;
	}
}
