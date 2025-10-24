import express  from 'express';
import { protectRoute } from '../middlewares/auth.middleware.js';
import { createChat, deletechat, getchats } from '../controllers/chat.controller.js';

const router = express.Router();

router.post("/create",protectRoute,createChat);
router.get("/getchats",protectRoute,getchats);
router.delete("/deletechat",protectRoute,deletechat);


export default router;