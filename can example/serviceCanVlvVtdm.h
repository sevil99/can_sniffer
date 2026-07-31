#ifndef __SERVICECANVLV_H
#define __SERVICECANVLV_H

#include "stdint.h"
#include "defines.h"
#include "global.h"
#include "can.h"
#include "can_aux_vlv.h"


#ifdef __cplusplus
 extern "C" {
#endif





void canVlv_Init(void);

void canVlv_sendPing(float temp);
//void canvlv_sendStart(void);
void canvlv_sendStop(void);
void canvlv_sendDeblock(void);
void canvlv_sendMdRequest(void);
void canvlv_sendParamCrcRequest(uint16_t vcuNum);
void canvlv_sendCfgOn(uint16_t vcuNum);
void canvlv_sendCfgAccept(void);
void canvlv_sendWriteParam(uint16_t index, uint32_t value);
	
/*
void can_sendParamVal(uint16_t paramCode);
void can_sendCfgReady(void);
void can_sendCfgConfirm(void);
void can_sendParamCrcval(void);
*/
void canVlv_execTx(void);
void canVlv_execRx(void);

#ifdef __cplusplus
}
#endif

#endif /* __SERVICECANVLV_H */
