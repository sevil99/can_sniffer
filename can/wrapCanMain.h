#ifndef __WRAPCANMAIN_H
#define __WRAPCANMAIN_H

#include "stdint.h"
#include "defines.h"
//#include "global.h"
#include "can.h"
//#include "serviceStatreg.h"
#include "squeue.h"


#ifdef __cplusplus
 extern "C" {
#endif


void wrapCanMainVTDM_init(uint16_t	_vtdm_num, squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx);
void wrapCanMainECU_init(uint16_t	_ecu_num, squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx);

void canMain_proceedRxMsg(void);

//void canMain_sendError(uint16_t error);
//void canMain_sendPing(float temp);

//void canMain_sendOpMode(void);

void canMain_sendPing(float temp);
void canMain_sendOpMode(void);
void canMain_sendStart(void);
void canMain_sendStop(void);
void canMain_sendDeblock(void);
void canMain_sendVtdmServStart(void);
void canMain_sendVtdmServStop(void);
void canMain_sendCdiServStart(void);
void canMain_sendCdiServStop(void);
void canMain_sendMdRequest(void);
void canMain_sendParamCrcRequest(uint16_t devNum);
void canMain_sendCfgOn(uint16_t devNum);
void canMain_sendCfgAccept(void);
void canMain_sendWriteParam(uint16_t index, uint32_t value);
void canMain_sendError(uint16_t  devNum, uint16_t error);

/*
void can_sendParamVal(uint16_t paramCode);
void can_sendCfgReady(void);
void can_sendCfgConfirm(void);
void can_sendParamCrcval(void);

void canMain_sendStatreg(StatRegVal_t* val);
*/

#ifdef __cplusplus
}
#endif

#endif /* __WRAPCANMAIN_H */
