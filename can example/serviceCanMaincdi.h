#ifndef __SERVICECANMAIN_H
#define __SERVICECANMAIN_H

#include "defines.h"
#include "global.h"
#include "fdcan.h"
#include "can_aux_main.h"
#include "can_aux_global.h"


#ifdef __cplusplus
 extern "C" {
#endif

_extern volatile uint16_t cfgMdDummy; 						//	временная тестовая переменная-заглушка


void canMain_Init(void);
void setCanBusFilters(void);

void canMain_sendPing(float temp);
void canMain_sendCdiCut(uint16_t val);
void canMain_sendOpMode(void);
void canMain_sendError(uint16_t error);

void canMain_execTx(void);
void canMain_execRx(void);

/*

*/


#ifdef __cplusplus
}
#endif

#endif /* __SERVICECANMAIN_H */
