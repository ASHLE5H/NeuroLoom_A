import express from 'express';
import { login, signup } from '../controllers/auth.controller.js';
import { protectRoute } from '../middlewares/auth.middleware.js';

const router = express.Router();

router.post("/signup",signup);

router.post("/login",login);

router.get("/me",protectRoute,(req,res)=>{
    res.status(200).json({success:"true",user:req.user})
})


export default router;