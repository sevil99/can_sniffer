#ifndef __WRAPCANVLV_H
#define __WRAPCANVLV_H

#include "stdint.h"
#include "defines.h"
#include "global.h"
#include "can.h"
#include "can_aux_vlv.h"
#include "squeue.h"



#ifdef __cplusplus
 extern "C" {
#endif


void wrapCanVlv_init(squeue_t* _can_squeu_Tx, squeue_t* _can_squeu_Rx);

void canVlv_proceedRxMsg(void);   

void canVlv_sendPing(float temp);
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

void canvlv_sendStart(void);
*/


#ifdef __cplusplus
}
#endif

#endif /* __WRAPCANVLV_H */
