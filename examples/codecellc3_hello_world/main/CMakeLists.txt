idf_component_register(SRCS "SEGGER_RTT.c" "SEGGER_RTT_printf.c" "hello_world_main.c"
                       PRIV_REQUIRES spi_flash app_trace driver
                       INCLUDE_DIRS ".")
