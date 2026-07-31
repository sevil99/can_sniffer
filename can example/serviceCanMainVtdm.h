#ifndef __SERVICECANMAIN_H
#define __SERVICECANMAIN_H

#include "stdint.h"
#include "defines.h"
#include "global.h"
#include "can.h"
#include "can_aux_main.h"
#include "serviceStatreg.h"

#ifdef __cplusplus
 extern "C" {
#endif





void canMain_Init(void);

void canMain_sendPing(float temp);
void canMain_sendStatreg(StatRegVal_t* val);
void canMain_sendOpMode(void);
void canMain_sendError(uint16_t error);
/*
void can_sendParamVal(uint16_t paramCode);
void can_sendCfgReady(void);
void can_sendCfgConfirm(void);
void can_sendParamCrcval(void);
*/
void canMain_execTx(void);
void canMain_execRx(void);

#ifdef __cplusplus
}
#endif

#endif /* __SERVICECANMAIN_H */
